/* Files: Windows paths over host directories, file handles, directory
 * enumeration and file mappings.
 *
 * The guest sees one drive. "C:\Games\The Void" is the read-mostly game
 * installation; profile folders and the rest of C: are writable directories
 * under the host data root. Every component is resolved case-insensitively,
 * as NTFS lookups are. */
#define _GNU_SOURCE
#include "host.h"
#include "fonts.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <fnmatch.h>
#include <strings.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define WIN_MAX_PATH 260

typedef struct { const char *win; char host[1024]; } mount_t;
static mount_t mounts[8];
static int mount_count;
static char game_root[1024], data_root[1024];
static char cwd[WIN_MAX_PATH] = "C:\\Games\\The Void\\bin\\win32";
static pthread_mutex_t cwd_lock = PTHREAD_MUTEX_INITIALIZER;

const char *void_root_dir(void) { return game_root; }
const char *void_data_dir(void) { return data_root; }

static void mkdirs(const char *path)
{
    char tmp[1024];
    snprintf(tmp, sizeof tmp, "%s", path);
    for (char *p = tmp + 1; *p; ++p) {
        if (*p == '/') { *p = 0; mkdir(tmp, 0775); *p = '/'; }
    }
    mkdir(tmp, 0775);
}

static void add_mount(const char *win, const char *host_fmt, const char *base)
{
    mount_t *m = &mounts[mount_count++];
    m->win = win;
    snprintf(m->host, sizeof m->host, host_fmt, base);
    mkdirs(m->host);
}

int void_files_init(const char *game, const char *data)
{
    snprintf(game_root, sizeof game_root, "%s", game);
    snprintf(data_root, sizeof data_root, "%s", data);
    /* Longest prefixes first. */
    add_mount("C:\\Users\\Player\\AppData\\Local\\Temp", "%s/Temp", data);
    add_mount("C:\\Users\\Player\\Documents", "%s/Documents", data);
    add_mount("C:\\Users\\Player\\AppData", "%s/AppData", data);
    add_mount("C:\\Users\\Public\\Documents", "%s/PublicDocuments", data);
    add_mount("C:\\ProgramData", "%s/ProgramData", data);
    add_mount("C:\\Games\\The Void", "%s", game);
    add_mount("C:", "%s/drive_c", data);
    struct stat st;
    if (stat(game_root, &st) || !S_ISDIR(st.st_mode)) {
        void_log("[void] game root %s is missing", game_root);
        return 0;
    }
    return 1;
}

/* Normalize a Windows path to "C:\a\b" (no trailing separator, no . or ..).
 * Returns 0 if it cannot be represented. */
static int normalize(const char *in, char *out, size_t cap)
{
    char work[1024];
    size_t n = 0;
    const char *p = in;
    if (!strncmp(p, "\\\\?\\", 4)) p += 4;
    if (((p[0] | 0x20) >= 'a' && (p[0] | 0x20) <= 'z') && p[1] == ':') {
        if (p[2] == '\\' || p[2] == '/') {
            snprintf(work, sizeof work, "C:%s", p + 2);
        } else {
            pthread_mutex_lock(&cwd_lock);
            snprintf(work, sizeof work, "%s\\%s", cwd, p + 2);
            pthread_mutex_unlock(&cwd_lock);
        }
    } else if (p[0] == '\\' || p[0] == '/') {
        snprintf(work, sizeof work, "C:%s", p);
    } else {
        pthread_mutex_lock(&cwd_lock);
        snprintf(work, sizeof work, "%s\\%s", cwd, p);
        pthread_mutex_unlock(&cwd_lock);
    }
    /* Split and rebuild. */
    char *parts[128];
    int count = 0;
    for (char *s = work; *s; ++s) if (*s == '/') *s = '\\';
    char *save = NULL;
    char *tok = strtok_r(work + 2, "\\", &save);
    while (tok) {
        if (!strcmp(tok, ".") || !*tok) {
        } else if (!strcmp(tok, "..")) {
            if (count) --count;
        } else {
            /* Windows strips trailing dots and spaces from components. */
            size_t len = strlen(tok);
            while (len > 1 && (tok[len - 1] == '.' || tok[len - 1] == ' ')) tok[--len] = 0;
            if (count == 128) return 0;
            parts[count++] = tok;
        }
        tok = strtok_r(NULL, "\\", &save);
    }
    n = (size_t)snprintf(out, cap, "C:");
    for (int i = 0; i < count; ++i) {
        n += (size_t)snprintf(out + n, n < cap ? cap - n : 0, "\\%s", parts[i]);
        if (n >= cap) return 0;
    }
    if (count == 0) snprintf(out, cap, "C:\\");
    return 1;
}

/* Directory listings, read once. On Android's shared storage every lookup
 * is a round trip through FUSE, and the game probes many loose files that
 * are not there (a texture by language, then without, before its archive):
 * each miss listed the whole folder, seconds for a journal page. The
 * installation does not change while the game runs; other folders are read
 * again after a few seconds, and every change made through these functions
 * drops the cache. */
#define DIR_BUCKETS 512
#define DIR_TTL_MS 3000u
typedef struct dir_list {
    struct dir_list *next;
    uint32_t read_ms;
    int count, permanent;
    char **names;                       /* sorted case-insensitively */
    char path[];
} dir_list;
static dir_list *dir_table[DIR_BUCKETS];
static pthread_mutex_t dir_lock = PTHREAD_MUTEX_INITIALIZER;

static int name_order(const void *a, const void *b) { return strcasecmp(*(char *const *)a, *(char *const *)b); }

/* path is dir or inside it. The installation is what is under the game's
 * root but not under the profile: the launcher takes any folder holding
 * the game, also one that holds the profile (the game copied straight into
 * /sdcard/TheVoid, beside userdata). */
static int under(const char *path, const char *dir)
{
    size_t n = strlen(dir);
    return n && !strncmp(path, dir, n) && (path[n] == 0 || path[n] == '/');
}

static void dir_free(dir_list *d)
{
    for (int i = 0; i < d->count; ++i) free(d->names[i]);
    free(d->names);
    free(d);
}

void void_files_changed(void)
{
    pthread_mutex_lock(&dir_lock);
    for (int i = 0; i < DIR_BUCKETS; ++i) {
        for (dir_list *d = dir_table[i], *n; d; d = n) { n = d->next; dir_free(d); }
        dir_table[i] = NULL;
    }
    pthread_mutex_unlock(&dir_lock);
}

static dir_list *dir_read(const char *path)
{
    DIR *dir = opendir(path);
    if (!dir) return NULL;
    size_t len = strlen(path);
    dir_list *d = (dir_list *)calloc(1, sizeof *d + len + 1);
    memcpy(d->path, path, len + 1);
    int cap = 0;
    struct dirent *e;
    while ((e = readdir(dir))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        if (d->count == cap) {
            cap = cap ? cap * 2 : 16;
            d->names = (char **)realloc(d->names, (size_t)cap * sizeof *d->names);
        }
        d->names[d->count++] = strdup(e->d_name);
    }
    closedir(dir);
    if (d->count > 1) qsort(d->names, (size_t)d->count, sizeof *d->names, name_order);
    d->permanent = under(path, game_root) && !under(path, data_root);
    return d;
}

/* 1 if folder `dir` holds `name` case-insensitively (its own spelling, the
 * exact one first, to `out`), 0 if not, -1 if the folder cannot be listed. */
static int dir_lookup(const char *dir, const char *name, char *out, size_t cap)
{
    uint32_t h = 2166136261u;
    for (const char *s = dir; *s; ++s) h = (h ^ (uint8_t)*s) * 16777619u;
    dir_list **slot = &dir_table[h % DIR_BUCKETS];
    uint32_t now = void_tick_ms();
    pthread_mutex_lock(&dir_lock);
    dir_list **link = slot, *d;
    for (d = *link; d; link = &d->next, d = d->next)
        if (!strcmp(d->path, dir)) break;
    if (d && !d->permanent && now - d->read_ms > DIR_TTL_MS) {
        *link = d->next;
        dir_free(d);
        d = NULL;
    }
    if (!d) {
        d = dir_read(dir);
        if (!d) { pthread_mutex_unlock(&dir_lock); return -1; }
        d->read_ms = now;
        d->next = *slot;
        *slot = d;
    }
    int lo = 0, hi = d->count - 1, at = -1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2, c = strcasecmp(name, d->names[mid]);
        if (!c) { at = mid; break; }
        if (c < 0) hi = mid - 1; else lo = mid + 1;
    }
    if (at >= 0) {
        while (at > 0 && !strcasecmp(name, d->names[at - 1])) --at;
        int pick = at;
        for (int i = at; i < d->count && !strcasecmp(name, d->names[i]); ++i)
            if (!strcmp(name, d->names[i])) { pick = i; break; }
        snprintf(out, cap, "%s", d->names[pick]);
    }
    pthread_mutex_unlock(&dir_lock);
    return at >= 0;
}

/* Append component `name` to host path `base`, matching an existing entry
 * case-insensitively. Returns 1 if the entry exists. */
static int resolve_component(char *base, size_t cap, const char *name)
{
    size_t len = strlen(base);
    char own[256];
    int found = dir_lookup(len ? base : "/", name, own, sizeof own);
    if (found < 0) {
        /* A folder one may enter but not list: the exact spelling only. */
        snprintf(base + len, cap - len, "/%s", name);
        struct stat st;
        return !lstat(base, &st);
    }
    snprintf(base + len, cap - len, "/%s", found ? own : name);
    return found;
}

/* The port's own versions of game files (patched scripts the activity puts
 * in <data>/overrides for the running release): the game looks for loose
 * files under data\ before its archives, so an existing override wins. */
static char *override_path(const char *norm)
{
    static const char prefix[] = "C:\\Games\\The Void\\data\\";
    if (strncasecmp(norm, prefix, sizeof prefix - 1)) return NULL;
    char *host = (char *)malloc(2048);
    snprintf(host, 2048, "%s/overrides", data_root);
    const char *rest = norm + sizeof prefix - 1;
    char component[512];
    while (*rest) {
        size_t k = 0;
        while (rest[k] && rest[k] != '\\' && k < sizeof component - 1) { component[k] = rest[k]; ++k; }
        component[k] = 0;
        rest += k;
        while (*rest == '\\') ++rest;
        if (!resolve_component(host, 2048, component)) { free(host); return NULL; }
    }
    struct stat st;
    if (stat(host, &st) || !S_ISREG(st.st_mode)) { free(host); return NULL; }
    return host;
}

/* Windows path (UTF-8) -> host path. *exists_parent reports whether every
 * component but the last exists (ERROR_PATH_NOT_FOUND vs FILE_NOT_FOUND),
 * *exists whether the last one does too. */
static char *to_host_found(const char *windows_path, int *parent_exists, char *normalized_out, int *exists)
{
    char norm[1024];
    if (!windows_path || !normalize(windows_path, norm, sizeof norm)) return NULL;
    if (normalized_out) snprintf(normalized_out, 1024, "%s", norm);
    char *over = void_fonts_path(norm);
    if (!over) over = override_path(norm);
    if (over) {
        if (parent_exists) *parent_exists = 1;
        if (exists) *exists = 1;
        static int logged;
        if (logged++ < 32) void_log("[void] %s: the port's override %s", norm, over);
        return over;
    }
    const mount_t *best = NULL;
    size_t best_len = 0;
    for (int i = 0; i < mount_count; ++i) {
        size_t l = strlen(mounts[i].win);
        if (!strncasecmp(norm, mounts[i].win, l) && (norm[l] == 0 || norm[l] == '\\') && l > best_len) {
            best = &mounts[i];
            best_len = l;
        }
    }
    if (!best) return NULL;
    char *host = (char *)malloc(2048);
    snprintf(host, 2048, "%s", best->host);
    const char *rest = norm + best_len;
    int ok = 1, found = 1;
    char component[512];
    while (*rest) {
        while (*rest == '\\') ++rest;
        if (!*rest) break;
        size_t k = 0;
        while (rest[k] && rest[k] != '\\' && k < sizeof component - 1) { component[k] = rest[k]; ++k; }
        component[k] = 0;
        rest += k;
        int last = !*rest || (rest[0] == '\\' && !rest[1]);
        if (!ok) {
            size_t len = strlen(host);
            snprintf(host + len, 2048 - len, "/%s", component);
        } else {
            found = resolve_component(host, 2048, component);
            if (!found && !last) ok = 0;
        }
    }
    if (parent_exists) *parent_exists = ok;
    if (exists) *exists = ok && found;
    return host;
}

static char *to_host(const char *windows_path, int *parent_exists, char *normalized_out)
{
    return to_host_found(windows_path, parent_exists, normalized_out, NULL);
}

char *void_path_to_host(const char *windows_path) { return to_host(windows_path, NULL, NULL); }

uint32_t void_cwd_get(char *out, uint32_t cap)
{
    pthread_mutex_lock(&cwd_lock);
    uint32_t n = (uint32_t)snprintf(out, cap, "%s", cwd);
    pthread_mutex_unlock(&cwd_lock);
    return n;
}

int void_cwd_set(const char *windows_path)
{
    char norm[1024];
    if (!normalize(windows_path, norm, sizeof norm)) return 0;
    char *host = to_host(norm, NULL, NULL);
    struct stat st;
    int ok = host && !stat(host, &st) && S_ISDIR(st.st_mode);
    free(host);
    if (!ok) return 0;
    pthread_mutex_lock(&cwd_lock);
    snprintf(cwd, sizeof cwd, "%s", norm);
    pthread_mutex_unlock(&cwd_lock);
    return 1;
}

uint32_t void_errno_to_win32(int e)
{
    switch (e) {
    case ENOENT: return ERROR_FILE_NOT_FOUND_;
    case ENOTDIR: return ERROR_PATH_NOT_FOUND_;
    case EACCES: case EPERM: case EROFS: return ERROR_ACCESS_DENIED_;
    case EEXIST: return ERROR_FILE_EXISTS_;
    case ENOMEM: return ERROR_NOT_ENOUGH_MEMORY_;
    case EBADF: return ERROR_INVALID_HANDLE_;
    case EINVAL: return ERROR_INVALID_PARAMETER_;
    case ENOSPC: return 112u;          /* ERROR_DISK_FULL */
    case ENOTEMPTY: return 145u;       /* ERROR_DIR_NOT_EMPTY */
    default: return ERROR_ACCESS_DENIED_;
    }
}

/* ----------------------------------------------------------- file objects */
typedef struct {
    int fd;
    int std_stream;       /* 0 none, 1 stdin, 2 stdout, 3 stderr */
    int is_dir;
    char *host_path;
    int delete_on_close;
    int shared;           /* fd is an installation file's shared descriptor */
    int64_t pos, size;    /* a shared handle's own position; the file's size */
    char line[512];       /* buffered guest console output */
    size_t line_len;
} file_t;

/* The installation's files, opened once. The game's archive reader opens
 * Properties.vfs and the others again for every file it takes out (five
 * hundred times while a save loads), and each open, stat and close is a
 * round trip through FUSE. Handles opened for reading share one descriptor
 * that is never closed; each keeps its own position and reads with pread. */
#define SHARED_MAX 64
static struct { char *path; int fd; int64_t size; } shared_files[SHARED_MAX];
static int shared_count;
static pthread_mutex_t shared_lock = PTHREAD_MUTEX_INITIALIZER;

static int in_installation(const char *host)
{
    return under(host, game_root) && strcmp(host, game_root) && !under(host, data_root);
}

/* The shared descriptor of regular file `host`, or -1. */
static int shared_open(const char *host, int64_t *size)
{
    int fd = -1;
    pthread_mutex_lock(&shared_lock);
    for (int i = 0; i < shared_count && fd < 0; ++i)
        if (!strcmp(shared_files[i].path, host)) { fd = shared_files[i].fd; *size = shared_files[i].size; }
    if (fd < 0 && shared_count < SHARED_MAX) {
        fd = open(host, O_RDONLY | O_CLOEXEC);
        struct stat st;
        if (fd >= 0 && (fstat(fd, &st) || !S_ISREG(st.st_mode))) { close(fd); fd = -1; }
        if (fd >= 0) {
            shared_files[shared_count].path = strdup(host);
            shared_files[shared_count].fd = fd;
            shared_files[shared_count++].size = *size = (int64_t)st.st_size;
        }
    }
    pthread_mutex_unlock(&shared_lock);
    return fd;
}

static void file_destroy(void_object *o)
{
    file_t *f = (file_t *)o->data;
    if (f->fd >= 0 && !f->std_stream && !f->shared) close(f->fd);
    if (f->delete_on_close && f->host_path && !unlink(f->host_path)) void_files_changed();
    free(f->host_path);
}

static uint32_t file_handle(int fd, const char *host_path, int std_stream)
{
    void_object *o = void_object_new(VOID_OBJ_FILE, sizeof(file_t));
    file_t *f = (file_t *)o->data;
    f->fd = fd;
    f->std_stream = std_stream;
    f->host_path = host_path ? strdup(host_path) : NULL;
    o->destroy = file_destroy;
    o->signaled = 1;
    return void_handle_new(o);
}

static file_t *file_get(uint32_t h)
{
    void_object *o = void_handle_get(h, VOID_OBJ_FILE);
    return o ? (file_t *)o->data : NULL;
}

int void_file_host_fd(uint32_t h)
{
    file_t *f = file_get(h);
    return f ? f->fd : -1;
}

static uint32_t std_handles[3];

void void_files_std_init(void)
{
    std_handles[0] = file_handle(0, NULL, 1);
    std_handles[1] = file_handle(1, NULL, 2);
    std_handles[2] = file_handle(2, NULL, 3);
}

#define GENERIC_READ_ 0x80000000u
#define GENERIC_WRITE_ 0x40000000u
#define FILE_WRITE_DATA_ 0x0002u
#define FILE_APPEND_DATA_ 0x0004u
#define CREATE_NEW_ 1u
#define CREATE_ALWAYS_ 2u
#define OPEN_EXISTING_ 3u
#define OPEN_ALWAYS_ 4u
#define TRUNCATE_EXISTING_ 5u
#define FILE_FLAG_DELETE_ON_CLOSE_ 0x04000000u
#define FILE_FLAG_BACKUP_SEMANTICS_ 0x02000000u

static uint32_t create_file(const char *path, uint32_t access, uint32_t disposition, uint32_t flags)
{
    if (!path || !*path) { void_set_last_error(ERROR_PATH_NOT_FOUND_); return WIN_INVALID_HANDLE; }
    if (!strncasecmp(path, "\\\\.\\", 4) || !strcasecmp(path, "CONOUT$") || !strcasecmp(path, "CONIN$")) {
        void_log("[void] CreateFile(%s): device paths are not supported", path);
        void_set_last_error(ERROR_FILE_NOT_FOUND_);
        return WIN_INVALID_HANDLE;
    }
    int parent_ok = 0, listed = 0;
    char *host = to_host_found(path, &parent_ok, NULL, &listed);
    if (!host) { void_set_last_error(ERROR_PATH_NOT_FOUND_); return WIN_INVALID_HANDLE; }
    if (!listed && (disposition == OPEN_EXISTING_ || disposition == TRUNCATE_EXISTING_)) {
        /* A probe for a loose file that is not there: no trip to the disk. */
        free(host);
        void_set_last_error(parent_ok ? ERROR_FILE_NOT_FOUND_ : ERROR_PATH_NOT_FOUND_);
        return WIN_INVALID_HANDLE;
    }
    int write = (access & (GENERIC_WRITE_ | FILE_WRITE_DATA_ | FILE_APPEND_DATA_ | 0x10000000u)) != 0;
    if (listed && !write && (disposition == OPEN_EXISTING_ || disposition == OPEN_ALWAYS_)
        && !(flags & FILE_FLAG_DELETE_ON_CLOSE_) && in_installation(host)) {
        int64_t size = 0;
        int fd = shared_open(host, &size);
        if (fd >= 0) {
            uint32_t h = file_handle(fd, host, 0);
            file_t *f = file_get(h);
            f->shared = 1;
            f->size = size;
            free(host);
            void_set_last_error(disposition == OPEN_ALWAYS_ ? ERROR_ALREADY_EXISTS_ : 0);
            return h;
        }
    }
    struct stat st;
    int exists = listed && !stat(host, &st);
    if (exists && S_ISDIR(st.st_mode)) {
        if (!(flags & FILE_FLAG_BACKUP_SEMANTICS_)) {
            free(host);
            void_set_last_error(ERROR_ACCESS_DENIED_);
            return WIN_INVALID_HANDLE;
        }
        int fd = open(host, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
        uint32_t h = fd >= 0 ? file_handle(fd, host, 0) : WIN_INVALID_HANDLE;
        if (fd >= 0) file_get(h)->is_dir = 1;
        else void_set_last_error(void_errno_to_win32(errno));
        free(host);
        return h;
    }
    int read = (access & (GENERIC_READ_ | 0x0001u | 0x10000000u)) != 0 || !write;
    int oflags = O_CLOEXEC | (write ? (read ? O_RDWR : O_WRONLY) : O_RDONLY);
    switch (disposition) {
    case CREATE_NEW_: oflags |= O_CREAT | O_EXCL; break;
    case CREATE_ALWAYS_: oflags |= O_CREAT | O_TRUNC; break;
    case OPEN_EXISTING_: break;
    case OPEN_ALWAYS_: oflags |= O_CREAT; break;
    case TRUNCATE_EXISTING_: oflags |= O_TRUNC; break;
    default:
        free(host);
        void_set_last_error(ERROR_INVALID_PARAMETER_);
        return WIN_INVALID_HANDLE;
    }
    if ((oflags & O_CREAT) && !write) oflags = (oflags & ~O_ACCMODE) | O_RDWR;
    int fd = open(host, oflags, 0664);
    if (fd < 0) {
        int e = errno;
        uint32_t code = void_errno_to_win32(e);
        if (e == ENOENT && !parent_ok) code = ERROR_PATH_NOT_FOUND_;
        VLOG("[void] CreateFile(%s -> %s) failed: %s", path, host, strerror(e));
        free(host);
        void_set_last_error(code);
        return WIN_INVALID_HANDLE;
    }
    if (!exists) void_files_changed();
    uint32_t h = file_handle(fd, host, 0);
    if (flags & FILE_FLAG_DELETE_ON_CLOSE_) file_get(h)->delete_on_close = 1;
    VLOG("[void] CreateFile(%s) -> %s handle %08X", path, host, h);
    free(host);
    void_set_last_error((exists && (disposition == CREATE_ALWAYS_ || disposition == OPEN_ALWAYS_)) ? ERROR_ALREADY_EXISTS_ : 0);
    return h;
}

#define K32 "kernel32.dll"

WINAPI_EXPORT(K32, CreateFileA, 7)
{
    char *path = void_astr_utf8(ARG(0));
    uint32_t h = create_file(path, ARG(1), ARG(4), ARG(5));
    free(path);
    return h;
}

WINAPI_EXPORT(K32, CreateFileW, 7)
{
    char *path = void_wstr_utf8(ARG(0));
    uint32_t h = create_file(path, ARG(1), ARG(4), ARG(5));
    free(path);
    return h;
}

static void console_write(file_t *f, const uint8_t *data, uint32_t n)
{
    for (uint32_t i = 0; i < n; ++i) {
        char c = (char)data[i];
        if (c == '\n' || f->line_len == sizeof f->line - 1) {
            f->line[f->line_len] = 0;
            void_log("[guest-%s] %s", f->std_stream == 3 ? "stderr" : "stdout", f->line);
            f->line_len = 0;
            if (c == '\n') continue;
        }
        if (c != '\r') f->line[f->line_len++] = c;
    }
}

WINAPI_EXPORT(K32, ReadFile, 5)
{
    uint32_t h = ARG(0), buffer = ARG(1), size = ARG(2), read_out = ARG(3), overlapped = ARG(4);
    file_t *f = file_get(h);
    if (read_out) MEM32(read_out) = 0;
    if (!f || f->is_dir) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (f->std_stream) return 1;
    if (size && !void_vm_writable(buffer, size)) { void_set_last_error(998u); return 0; }  /* ERROR_NOACCESS */
    ssize_t got;
    int blocking = size >= 65536;
    if (blocking) void_blocking_begin();
    if (overlapped) {
        off_t offset = (off_t)MEM32(overlapped + 8) | ((off_t)MEM32(overlapped + 12) << 32);
        got = pread(f->fd, GPTR(buffer), size, offset);
        if (f->shared && got >= 0) f->pos = (int64_t)offset + got;
    } else if (f->shared) {
        size_t total = 0;
        got = 0;
        while (total < size) {
            ssize_t r = pread(f->fd, (uint8_t *)GPTR(buffer) + total, size - total, (off_t)(f->pos + (int64_t)total));
            if (r < 0) { if (errno == EINTR) continue; got = -1; break; }
            if (r == 0) break;
            total += (size_t)r;
        }
        if (got >= 0) { got = (ssize_t)total; f->pos += (int64_t)total; }
    } else {
        size_t total = 0;
        got = 0;
        while (total < size) {
            ssize_t r = read(f->fd, (uint8_t *)GPTR(buffer) + total, size - total);
            if (r < 0) { if (errno == EINTR) continue; got = -1; break; }
            if (r == 0) break;
            total += (size_t)r;
        }
        if (got >= 0) got = (ssize_t)total;
    }
    int e = errno;
    if (blocking) void_blocking_end();
    if (got < 0) { void_set_last_error(void_errno_to_win32(e)); return 0; }
    if (read_out) MEM32(read_out) = (uint32_t)got;
    if (overlapped) { MEM32(overlapped) = 0; MEM32(overlapped + 4) = (uint32_t)got; }
    return 1;
}

WINAPI_EXPORT(K32, WriteFile, 5)
{
    uint32_t h = ARG(0), buffer = ARG(1), size = ARG(2), written_out = ARG(3), overlapped = ARG(4);
    file_t *f = file_get(h);
    if (written_out) MEM32(written_out) = 0;
    if (!f || f->is_dir) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (f->std_stream) {
        console_write(f, (const uint8_t *)GPTR(buffer), size);
        if (written_out) MEM32(written_out) = size;
        return 1;
    }
    if (f->shared) { void_set_last_error(ERROR_ACCESS_DENIED_); return 0; }
    ssize_t put;
    if (overlapped) {
        off_t offset = (off_t)MEM32(overlapped + 8) | ((off_t)MEM32(overlapped + 12) << 32);
        put = pwrite(f->fd, GPTR(buffer), size, offset);
    } else {
        put = write(f->fd, GPTR(buffer), size);
    }
    if (put < 0) { void_set_last_error(void_errno_to_win32(errno)); return 0; }
    if (written_out) MEM32(written_out) = (uint32_t)put;
    return 1;
}

static off_t shared_seek(file_t *f, int64_t distance, int whence)
{
    int64_t pos = (whence == SEEK_SET ? 0 : whence == SEEK_CUR ? f->pos : f->size) + distance;
    if (pos < 0) return -1;
    f->pos = pos;
    return (off_t)pos;
}

WINAPI_EXPORT(K32, SetFilePointer, 4)
{
    file_t *f = file_get(ARG(0));
    if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0xFFFFFFFFu; }
    int64_t distance = ARG(2) ? (int64_t)(((uint64_t)MEM32(ARG(2)) << 32) | ARG(1)) : (int64_t)(int32_t)ARG(1);
    int whence = ARG(3) == 0 ? SEEK_SET : ARG(3) == 1 ? SEEK_CUR : SEEK_END;
    if (f->std_stream) return 0;
    off_t pos = f->shared ? shared_seek(f, distance, whence) : lseek(f->fd, (off_t)distance, whence);
    if (pos < 0) { void_set_last_error(131u); return 0xFFFFFFFFu; }   /* ERROR_NEGATIVE_SEEK */
    if (ARG(2)) MEM32(ARG(2)) = (uint32_t)((uint64_t)pos >> 32);
    void_set_last_error(0);
    return (uint32_t)pos;
}

WINAPI_EXPORT(K32, SetFilePointerEx, 5)
{
    file_t *f = file_get(ARG(0));
    if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    int64_t distance = (int64_t)(((uint64_t)ARG(2) << 32) | ARG(1));
    int whence = ARG(4) == 0 ? SEEK_SET : ARG(4) == 1 ? SEEK_CUR : SEEK_END;
    off_t pos = f->shared ? shared_seek(f, distance, whence) : lseek(f->fd, (off_t)distance, whence);
    if (pos < 0) { void_set_last_error(131u); return 0; }
    if (ARG(3)) { MEM32(ARG(3)) = (uint32_t)pos; MEM32(ARG(3) + 4) = (uint32_t)((uint64_t)pos >> 32); }
    return 1;
}

WINAPI_EXPORT(K32, GetFileSize, 2)
{
    file_t *f = file_get(ARG(0));
    struct stat st;
    if (f && f->shared) st.st_size = (off_t)f->size;
    else if (!f || fstat(f->fd, &st)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0xFFFFFFFFu; }
    if (ARG(1)) MEM32(ARG(1)) = (uint32_t)((uint64_t)st.st_size >> 32);
    void_set_last_error(0);
    return (uint32_t)st.st_size;
}

WINAPI_EXPORT(K32, GetFileSizeEx, 2)
{
    file_t *f = file_get(ARG(0));
    struct stat st;
    if (f && f->shared) st.st_size = (off_t)f->size;
    else if (!f || fstat(f->fd, &st)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    MEM32(ARG(1)) = (uint32_t)st.st_size;
    MEM32(ARG(1) + 4) = (uint32_t)((uint64_t)st.st_size >> 32);
    return 1;
}

WINAPI_EXPORT(K32, GetFileType, 1)
{
    file_t *f = file_get(ARG(0));
    if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    return f->std_stream ? 2u : 1u;    /* FILE_TYPE_CHAR / FILE_TYPE_DISK */
}

WINAPI_EXPORT(K32, FlushFileBuffers, 1) { return file_get(ARG(0)) ? 1u : 0u; }

WINAPI_EXPORT(K32, SetEndOfFile, 1)
{
    file_t *f = file_get(ARG(0));
    if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (f->shared) { void_set_last_error(ERROR_ACCESS_DENIED_); return 0; }
    off_t pos = lseek(f->fd, 0, SEEK_CUR);
    if (pos < 0 || ftruncate(f->fd, pos)) { void_set_last_error(void_errno_to_win32(errno)); return 0; }
    return 1;
}

WINAPI_EXPORT(K32, LockFile, 5) { return 1; }
WINAPI_EXPORT(K32, UnlockFile, 5) { return 1; }
WINAPI_EXPORT(K32, LockFileEx, 6) { return 1; }

WINAPI_EXPORT(K32, GetStdHandle, 1)
{
    switch (ARG(0)) {
    case 0xFFFFFFF6u: return std_handles[0];
    case 0xFFFFFFF5u: return std_handles[1];
    case 0xFFFFFFF4u: return std_handles[2];
    default: void_set_last_error(ERROR_INVALID_HANDLE_); return WIN_INVALID_HANDLE;
    }
}

WINAPI_EXPORT(K32, SetStdHandle, 2)
{
    switch (ARG(0)) {
    case 0xFFFFFFF6u: std_handles[0] = ARG(1); return 1;
    case 0xFFFFFFF5u: std_handles[1] = ARG(1); return 1;
    case 0xFFFFFFF4u: std_handles[2] = ARG(1); return 1;
    default: return 0;
    }
}

static uint32_t attributes_of(const char *path)
{
    if (!path) { void_set_last_error(ERROR_PATH_NOT_FOUND_); return 0xFFFFFFFFu; }
    int parent_ok = 0, listed = 0;
    char *host = to_host_found(path, &parent_ok, NULL, &listed);
    struct stat st;
    if (!host || !listed || stat(host, &st)) {
        void_set_last_error(parent_ok ? ERROR_FILE_NOT_FOUND_ : ERROR_PATH_NOT_FOUND_);
        VLOG("[void] GetFileAttributes(%s): missing", path);
        free(host);
        return 0xFFFFFFFFu;
    }
    free(host);
    if (S_ISDIR(st.st_mode)) return 0x10u;
    return 0x20u;                       /* FILE_ATTRIBUTE_ARCHIVE */
}

WINAPI_EXPORT(K32, GetFileAttributesA, 1)
{
    char *path = void_astr_utf8(ARG(0));
    uint32_t r = attributes_of(path);
    free(path);
    return r;
}

WINAPI_EXPORT(K32, GetFileAttributesW, 1)
{
    char *path = void_wstr_utf8(ARG(0));
    uint32_t r = attributes_of(path);
    free(path);
    return r;
}

static uint32_t delete_file(const char *path)
{
    char *host = to_host(path, NULL, NULL);
    int ok = host && !unlink(host);
    if (ok) void_files_changed();
    else void_set_last_error(void_errno_to_win32(errno));
    free(host);
    return ok;
}

WINAPI_EXPORT(K32, DeleteFileA, 1) { char *p = void_astr_utf8(ARG(0)); uint32_t r = delete_file(p); free(p); return r; }
WINAPI_EXPORT(K32, DeleteFileW, 1) { char *p = void_wstr_utf8(ARG(0)); uint32_t r = delete_file(p); free(p); return r; }

static uint32_t move_file(const char *from, const char *to)
{
    char *a = to_host(from, NULL, NULL), *b = to_host(to, NULL, NULL);
    struct stat st;
    int ok = 0;
    if (a && b) {
        if (!stat(b, &st)) void_set_last_error(ERROR_ALREADY_EXISTS_);
        else if (rename(a, b)) void_set_last_error(void_errno_to_win32(errno));
        else { ok = 1; void_files_changed(); }
    }
    free(a); free(b);
    return ok;
}

WINAPI_EXPORT(K32, MoveFileA, 2)
{
    char *a = void_astr_utf8(ARG(0)), *b = void_astr_utf8(ARG(1));
    uint32_t r = move_file(a, b);
    free(a); free(b);
    return r;
}

WINAPI_EXPORT(K32, MoveFileW, 2)
{
    char *a = void_wstr_utf8(ARG(0)), *b = void_wstr_utf8(ARG(1));
    uint32_t r = move_file(a, b);
    free(a); free(b);
    return r;
}

WINAPI_EXPORT(K32, CreateDirectoryW, 2)
{
    char *path = void_wstr_utf8(ARG(0));
    char *host = to_host(path, NULL, NULL);
    uint32_t ok = 0;
    if (host) {
        if (!mkdir(host, 0775)) { ok = 1; void_files_changed(); }
        else void_set_last_error(errno == EEXIST ? ERROR_ALREADY_EXISTS_ : void_errno_to_win32(errno));
    } else {
        void_set_last_error(ERROR_PATH_NOT_FOUND_);
    }
    VLOG("[void] CreateDirectoryW(%s) = %u", path, ok);
    free(host); free(path);
    return ok;
}

WINAPI_EXPORT(K32, CreateDirectoryA, 2)
{
    char *path = void_astr_utf8(ARG(0));
    char *host = to_host(path, NULL, NULL);
    uint32_t ok = 0;
    if (host) {
        if (!mkdir(host, 0775)) { ok = 1; void_files_changed(); }
        else void_set_last_error(errno == EEXIST ? ERROR_ALREADY_EXISTS_ : void_errno_to_win32(errno));
    }
    free(host); free(path);
    return ok;
}

/* GetFullPathName: the normalized absolute Windows path. */
static uint32_t full_path(const char *in, uint32_t buffer, uint32_t capacity, uint32_t file_part, int wide)
{
    char norm[1024];
    if (!in || !normalize(in, norm, sizeof norm)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    /* Keep a trailing separator the caller supplied. */
    size_t in_len = strlen(in);
    if (in_len && (in[in_len - 1] == '\\' || in[in_len - 1] == '/') && strlen(norm) > 3) strcat(norm, "\\");
    uint32_t written = wide ? void_utf8_to_gw(norm, buffer, capacity) : void_utf8_to_ga(norm, buffer, capacity);
    uint32_t units = 0;
    if (wide) { if (written + 1 > capacity) return written; units = written; }
    else { if (written + 1 > capacity) return written; units = written; }
    if (file_part) {
        uint32_t last = 0;
        for (uint32_t i = 0; i < units; ++i) {
            uint32_t c = wide ? MEM16(buffer + 2 * i) : MEM8(buffer + i);
            if (c == '\\') last = i + 1;
        }
        MEM32(file_part) = last < units ? buffer + (wide ? 2 * last : last) : 0;
    }
    return units;
}

WINAPI_EXPORT(K32, GetFullPathNameA, 4)
{
    char *p = void_astr_utf8(ARG(0));
    uint32_t r = full_path(p, ARG(2), ARG(1), ARG(3), 0);
    free(p);
    return r;
}

WINAPI_EXPORT(K32, GetFullPathNameW, 4)
{
    char *p = void_wstr_utf8(ARG(0));
    uint32_t r = full_path(p, ARG(2), ARG(1), ARG(3), 1);
    free(p);
    return r;
}

static const char temp_dir[] = "C:\\Users\\Player\\AppData\\Local\\Temp\\";

WINAPI_EXPORT(K32, GetTempPathA, 2)
{
    uint32_t n = void_utf8_to_ga(temp_dir, ARG(1), ARG(0));
    return n;
}

WINAPI_EXPORT(K32, GetTempPathW, 2)
{
    uint32_t n = void_utf8_to_gw(temp_dir, ARG(1), ARG(0));
    return n;
}

static uint32_t temp_file_name(const char *dir, const char *prefix, uint32_t unique, char *out, size_t cap)
{
    static uint32_t counter;
    uint32_t number = unique ? unique : (uint32_t)(void_tick_ms() + ++counter) & 0xFFFFu;
    for (int attempt = 0; attempt < 65536; ++attempt) {
        if (!number) number = 1;
        snprintf(out, cap, "%s%s%.3s%X.tmp", dir, (dir[0] && dir[strlen(dir) - 1] == '\\') ? "" : "\\", prefix ? prefix : "", number);
        if (unique) return number;
        char *host = to_host(out, NULL, NULL);
        int fd = host ? open(host, O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0664) : -1;
        free(host);
        if (fd >= 0) { close(fd); void_files_changed(); return number; }
        number = (number + 1) & 0xFFFFu;
    }
    return 0;
}

WINAPI_EXPORT(K32, GetTempFileNameA, 4)
{
    char *dir = void_astr_utf8(ARG(0)), *prefix = void_astr_utf8(ARG(1));
    char name[1024];
    uint32_t r = temp_file_name(dir ? dir : "", prefix, ARG(2), name, sizeof name);
    if (r) void_utf8_to_ga(name, ARG(3), WIN_MAX_PATH);
    free(dir); free(prefix);
    return r;
}

WINAPI_EXPORT(K32, GetTempFileNameW, 4)
{
    char *dir = void_wstr_utf8(ARG(0)), *prefix = void_wstr_utf8(ARG(1));
    char name[1024];
    uint32_t r = temp_file_name(dir ? dir : "", prefix, ARG(2), name, sizeof name);
    if (r) void_utf8_to_gw(name, ARG(3), WIN_MAX_PATH);
    free(dir); free(prefix);
    return r;
}

/* ------------------------------------------------------------ find files */
typedef struct {
    char **names;
    int count, next;
    char dir[2048];
} find_t;

static void find_destroy(void_object *o)
{
    find_t *f = (find_t *)o->data;
    for (int i = 0; i < f->count; ++i) free(f->names[i]);
    free(f->names);
}

static uint64_t unix_to_filetime(time_t t, long ns)
{
    return (uint64_t)t * 10000000ull + (uint64_t)ns / 100u + 116444736000000000ull;
}

static int fill_find_data(find_t *f, const char *name, uint32_t out)
{
    char host[4096];
    snprintf(host, sizeof host, "%s/%s", f->dir, name);
    struct stat st;
    memset(GPTR(out), 0, 592);
    if (stat(host, &st)) return 0;
    MEM32(out) = S_ISDIR(st.st_mode) ? 0x10u : 0x20u;
    uint64_t ct = unix_to_filetime(st.st_ctim.tv_sec, st.st_ctim.tv_nsec);
    uint64_t at = unix_to_filetime(st.st_atim.tv_sec, st.st_atim.tv_nsec);
    uint64_t mt = unix_to_filetime(st.st_mtim.tv_sec, st.st_mtim.tv_nsec);
    MEM64(out + 4) = ct; MEM64(out + 12) = at; MEM64(out + 20) = mt;
    MEM32(out + 28) = S_ISDIR(st.st_mode) ? 0 : (uint32_t)((uint64_t)st.st_size >> 32);
    MEM32(out + 32) = S_ISDIR(st.st_mode) ? 0 : (uint32_t)st.st_size;
    void_utf8_to_gw(name, out + 44, 260);
    return 1;
}

WINAPI_EXPORT(K32, FindFirstFileW, 2)
{
    char *pattern_path = void_wstr_utf8(ARG(0));
    uint32_t out = ARG(1);
    if (!pattern_path) { void_set_last_error(ERROR_PATH_NOT_FOUND_); return WIN_INVALID_HANDLE; }
    char norm[1024];
    if (!normalize(pattern_path, norm, sizeof norm)) { free(pattern_path); void_set_last_error(ERROR_PATH_NOT_FOUND_); return WIN_INVALID_HANDLE; }
    char *slash = strrchr(norm, '\\');
    char pattern[512];
    snprintf(pattern, sizeof pattern, "%s", slash ? slash + 1 : norm);
    if (slash) *slash = 0;
    if (strlen(norm) == 2) strcat(norm, "\\");
    int parent_ok = 0;
    char *host_dir = to_host(norm, &parent_ok, NULL);
    DIR *d = host_dir ? opendir(host_dir) : NULL;
    if (!d) {
        VLOG("[void] FindFirstFileW(%s): no directory", pattern_path);
        free(host_dir); free(pattern_path);
        void_set_last_error(ERROR_PATH_NOT_FOUND_);
        return WIN_INVALID_HANDLE;
    }
    void_object *o = void_object_new(VOID_OBJ_FIND, sizeof(find_t));
    find_t *f = (find_t *)o->data;
    o->destroy = find_destroy;
    snprintf(f->dir, sizeof f->dir, "%s", host_dir);
    /* "*.*" matches every name, as on Windows. */
    int match_all = !strcmp(pattern, "*") || !strcmp(pattern, "*.*");
    struct dirent *e;
    while ((e = readdir(d))) {
        if (match_all || !fnmatch(pattern, e->d_name, FNM_CASEFOLD) ||
            (pattern[strlen(pattern) - 1] == '.' && !strchr(e->d_name, '.'))) {
            f->names = (char **)realloc(f->names, sizeof(char *) * (size_t)(f->count + 1));
            f->names[f->count++] = strdup(e->d_name);
        }
    }
    closedir(d);
    free(host_dir);
    VLOG("[void] FindFirstFileW(%s): %d matches", pattern_path, f->count);
    free(pattern_path);
    while (f->next < f->count && !fill_find_data(f, f->names[f->next], out)) ++f->next;
    if (f->next >= f->count) {
        void_object_release(o);
        void_set_last_error(ERROR_FILE_NOT_FOUND_);
        return WIN_INVALID_HANDLE;
    }
    ++f->next;
    return void_handle_new(o);
}

WINAPI_EXPORT(K32, FindNextFileW, 2)
{
    void_object *o = void_handle_get(ARG(0), VOID_OBJ_FIND);
    if (!o) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    find_t *f = (find_t *)o->data;
    while (f->next < f->count) {
        if (fill_find_data(f, f->names[f->next++], ARG(1))) return 1;
    }
    void_set_last_error(ERROR_NO_MORE_FILES_);
    return 0;
}

WINAPI_EXPORT(K32, FindClose, 1)
{
    if (!void_handle_get(ARG(0), VOID_OBJ_FIND)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    void_handle_close(ARG(0));
    return 1;
}

/* ------------------------------------------------------------- mappings */
typedef struct { int fd; uint64_t size; uint32_t protect; } mapping_t;

static void mapping_destroy(void_object *o)
{
    mapping_t *m = (mapping_t *)o->data;
    if (m->fd >= 0) close(m->fd);
}

WINAPI_EXPORT(K32, CreateFileMappingA, 6)
{
    uint32_t file = ARG(0), protect = ARG(2);
    uint64_t size = ((uint64_t)ARG(3) << 32) | ARG(4);
    int fd;
    if (file == WIN_INVALID_HANDLE) {
        char path[1100];
        snprintf(path, sizeof path, "%s/Temp/.mapping-XXXXXX", data_root);
        fd = mkstemp(path);
        if (fd < 0 || !size) { if (fd >= 0) close(fd); void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
        unlink(path);
        if (ftruncate(fd, (off_t)size)) { close(fd); void_set_last_error(ERROR_NOT_ENOUGH_MEMORY_); return 0; }
    } else {
        file_t *f = file_get(file);
        if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
        fd = dup(f->fd);
        struct stat st;
        fstat(fd, &st);
        if (!size) size = (uint64_t)st.st_size;
        else if (size > (uint64_t)st.st_size && (protect & 0xFFu) == 0x04u) {
            if (ftruncate(fd, (off_t)size)) { close(fd); void_set_last_error(ERROR_ACCESS_DENIED_); return 0; }
        }
    }
    void_object *o = void_object_new(VOID_OBJ_MAPPING, sizeof(mapping_t));
    mapping_t *m = (mapping_t *)o->data;
    m->fd = fd;
    m->size = size;
    m->protect = protect;
    o->destroy = mapping_destroy;
    void_set_last_error(0);
    return void_handle_new(o);
}

WINAPI_EXPORT(K32, OpenFileMappingA, 3)
{
    void_set_last_error(ERROR_FILE_NOT_FOUND_);
    return 0;
}

WINAPI_EXPORT(K32, MapViewOfFile, 5)
{
    void_object *o = void_handle_get(ARG(0), VOID_OBJ_MAPPING);
    if (!o) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    mapping_t *m = (mapping_t *)o->data;
    uint32_t access = ARG(1);
    uint64_t offset = ((uint64_t)ARG(2) << 32) | ARG(3);
    uint64_t size = ARG(4) ? ARG(4) : m->size - offset;
    if (offset > m->size || size > 0x7FFF0000u || !size) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    int writable = (access & 2u) != 0 || (access & 1u) != 0;
    int shared = !(access & 1u);           /* FILE_MAP_COPY is private */
    uint32_t va = void_vm_map_file(m->fd, offset, (uint32_t)size, writable, shared);
    VLOG("[void] MapViewOfFile(%08X, off %llX, %llX) = %08X", ARG(0), (unsigned long long)offset,
        (unsigned long long)size, va);
    return va;
}

WINAPI_EXPORT(K32, UnmapViewOfFile, 1) { return (uint32_t)void_vm_unmap_file(ARG(0)); }
