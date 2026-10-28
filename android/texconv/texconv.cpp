/* The launcher's texture converter: see texconv.h and tvtx.h. */
#include "texconv.h"
#include "tvtx.h"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#endif

#include "../../reference/astcenc/Source/astcenc.h"
#include "../../reference/etcpak/Decode.hpp"
#include "../../reference/etcpak/ProcessRGB.hpp"

namespace {

/* ------------------------------------------------------------- progress */

std::mutex progress_lock;
texconv_progress progress_state;
std::atomic<bool> cancelled{false};
std::atomic<int64_t> done_textures{0}, done_bytes{0};

void set_state(int state)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    progress_state.state = state;
}

int fail(const char *format, ...)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    va_list args;
    va_start(args, format);
    vsnprintf(progress_state.message, sizeof progress_state.message, format, args);
    va_end(args);
    progress_state.state = TEXCONV_FAILED;
    return -1;
}

void begin(int state, int64_t total, int64_t bytes)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    progress_state = texconv_progress{};
    progress_state.state = state;
    progress_state.total = total;
    progress_state.bytes_total = bytes;
    done_textures = 0;
    done_bytes = 0;
}

/* ----------------------------------------------------------------- files */

struct File {
#ifdef _WIN32
    HANDLE handle = INVALID_HANDLE_VALUE;
#else
    int fd = -1;
#endif
    File() = default;
    File(const File &) = delete;
    File &operator=(const File &) = delete;
    ~File() { close(); }

    bool open_read(const std::string &path)
    {
#ifdef _WIN32
        handle = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                             OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        return handle != INVALID_HANDLE_VALUE;
#else
        fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
        return fd >= 0;
#endif
    }

    bool create(const std::string &path)
    {
#ifdef _WIN32
        handle = CreateFileA(path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        return handle != INVALID_HANDLE_VALUE;
#else
        fd = ::open(path.c_str(), O_RDWR | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
        return fd >= 0;
#endif
    }

    /* Positional read of exactly `size` bytes (thread-safe). */
    bool read_at(void *buffer, size_t size, uint64_t offset) const
    {
        uint8_t *out = static_cast<uint8_t *>(buffer);
        while (size) {
#ifdef _WIN32
            OVERLAPPED at{};
            at.Offset = static_cast<DWORD>(offset);
            at.OffsetHigh = static_cast<DWORD>(offset >> 32);
            DWORD got = 0, want = size > 0x40000000u ? 0x40000000u : static_cast<DWORD>(size);
            if (!ReadFile(handle, out, want, &got, &at) || !got) return false;
#else
            ssize_t got = ::pread(fd, out, size > 0x40000000u ? 0x40000000u : size, static_cast<off_t>(offset));
            if (got < 0 && errno == EINTR) continue;
            if (got <= 0) return false;
#endif
            out += got;
            size -= static_cast<size_t>(got);
            offset += static_cast<uint64_t>(got);
        }
        return true;
    }

    bool write_at(const void *buffer, size_t size, uint64_t offset)
    {
        const uint8_t *in = static_cast<const uint8_t *>(buffer);
        while (size) {
#ifdef _WIN32
            OVERLAPPED at{};
            at.Offset = static_cast<DWORD>(offset);
            at.OffsetHigh = static_cast<DWORD>(offset >> 32);
            DWORD put = 0, want = size > 0x40000000u ? 0x40000000u : static_cast<DWORD>(size);
            if (!WriteFile(handle, in, want, &put, &at) || !put) return false;
#else
            ssize_t put = ::pwrite(fd, in, size > 0x40000000u ? 0x40000000u : size, static_cast<off_t>(offset));
            if (put < 0 && errno == EINTR) continue;
            if (put <= 0) return false;
#endif
            in += put;
            size -= static_cast<size_t>(put);
            offset += static_cast<uint64_t>(put);
        }
        return true;
    }

    uint64_t size() const
    {
#ifdef _WIN32
        LARGE_INTEGER value;
        return GetFileSizeEx(handle, &value) ? static_cast<uint64_t>(value.QuadPart) : 0;
#else
        struct stat st;
        return fstat(fd, &st) ? 0 : static_cast<uint64_t>(st.st_size);
#endif
    }

    bool sync()
    {
#ifdef _WIN32
        return FlushFileBuffers(handle) != 0;
#else
        return fsync(fd) == 0;
#endif
    }

    bool close()
    {
        bool ok = true;
#ifdef _WIN32
        if (handle != INVALID_HANDLE_VALUE) ok = CloseHandle(handle) != 0;
        handle = INVALID_HANDLE_VALUE;
#else
        if (fd >= 0) ok = ::close(fd) == 0;
        fd = -1;
#endif
        return ok;
    }
};

bool exists(const std::string &path)
{
#ifdef _WIN32
    return GetFileAttributesA(path.c_str()) != INVALID_FILE_ATTRIBUTES;
#else
    struct stat st;
    return stat(path.c_str(), &st) == 0;
#endif
}

bool remove_file(const std::string &path)
{
#ifdef _WIN32
    return DeleteFileA(path.c_str()) != 0 || GetLastError() == ERROR_FILE_NOT_FOUND;
#else
    return unlink(path.c_str()) == 0 || errno == ENOENT;
#endif
}

bool replace_file(const std::string &from, const std::string &to)
{
#ifdef _WIN32
    return MoveFileExA(from.c_str(), to.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
#else
    return rename(from.c_str(), to.c_str()) == 0;
#endif
}

int64_t free_space(const std::string &dir)
{
#ifdef _WIN32
    ULARGE_INTEGER available;
    return GetDiskFreeSpaceExA(dir.c_str(), &available, nullptr, nullptr) ? static_cast<int64_t>(available.QuadPart) : -1;
#else
    struct statvfs st;
    return statvfs(dir.c_str(), &st) ? -1 : static_cast<int64_t>(st.f_bavail) * static_cast<int64_t>(st.f_frsize);
#endif
}

std::string data_dir(const char *game) { return std::string(game) + "/data"; }
std::string pack_path(const char *game) { return data_dir(game) + "/" TVTX_FILE; }

/* ------------------------------------------------------- the container */

uint32_t le32(const uint8_t *p) { return tvtx_le32(p); }

/* The data/Textures.vfs layout (LP2C, as tools/build_vfs_index.py reads it):
 * "LP2C", u32 dirs, u32 files; each file: u8 name length, name, u32 size,
 * u32, u32 offset, u32 0, u32, u32; each directory: u8 name length, name,
 * u32 dirs, u32 files, its entries. */
struct Entry {
    std::string name;
    uint64_t offset, size;
};

struct Reader {
    const File &file;
    uint64_t at, end;
    bool read(void *out, size_t n)
    {
        if (at + n > end || !file.read_at(out, n, at)) return false;
        at += n;
        return true;
    }
};

bool read_directory(Reader &r, const std::string &parent, uint32_t dirs, uint32_t files, std::vector<Entry> &out, int depth)
{
    if (depth > 64) return false;
    for (uint32_t i = 0; i < files; ++i) {
        uint8_t length;
        char name[256];
        uint8_t fields[24];
        if (!r.read(&length, 1) || !r.read(name, length) || !r.read(fields, 24)) return false;
        Entry e{parent + "\\" + std::string(name, length), le32(fields + 8), le32(fields)};
        if (e.offset + e.size > r.end) return false;
        out.push_back(std::move(e));
    }
    for (uint32_t i = 0; i < dirs; ++i) {
        uint8_t length, counts[8];
        char name[256];
        if (!r.read(&length, 1) || !r.read(name, length) || !r.read(counts, 8)) return false;
        if (!read_directory(r, parent + "\\" + std::string(name, length), le32(counts), le32(counts + 4), out, depth + 1))
            return false;
    }
    return true;
}

bool read_container(const File &file, std::vector<Entry> &out)
{
    Reader r{file, 0, file.size()};
    uint8_t head[12];
    if (!r.read(head, 12) || memcmp(head, "LP2C", 4)) return false;
    return read_directory(r, "", le32(head + 4), le32(head + 8), out, 0);
}

bool is_tex(const std::string &name)
{
    if (name.size() < 4) return false;
    std::string tail = name.substr(name.size() - 4);
    for (char &c : tail) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return tail == ".tex";
}

/* A DXT DDS inside the container: a .tex of its own or a frame of one. */
struct Source {
    uint64_t offset;
    uint32_t bytes, block, width, height, mips, faces;
};

bool add_source(const File &file, uint64_t offset, uint64_t room, std::vector<Source> &out)
{
    uint8_t header[128];
    if (room < 128 || !file.read_at(header, 128, offset)) return false;
    tvtx_dds d;
    uint64_t bytes = tvtx_dds_bytes(header, room, &d);
    if (!bytes) return false;
    out.push_back(Source{offset, static_cast<uint32_t>(bytes), d.block, d.width, d.height, d.mips, d.faces});
    return true;
}

void collect_sources(const File &file, const std::vector<Entry> &entries, std::vector<Source> &out)
{
    for (const Entry &e : entries) {
        if (!is_tex(e.name) || e.size < 128) continue;
        uint8_t magic[4];
        if (!file.read_at(magic, 4, e.offset)) continue;
        if (!memcmp(magic, "DDS ", 4)) {
            add_source(file, e.offset, e.size, out);
            continue;
        }
        /* An animation: u32 frames, their u32 sizes, the frames' DDS files,
         * then u32 milliseconds and u8 looped (all 33 of the 2009 game's:
         * waters, drops, refractions; 5906 frames). */
        uint32_t frames = le32(magic);
        if (!frames || frames > 4096 || 4ull + 4ull * frames > e.size) continue;
        std::vector<uint8_t> sizes(4ull * frames);
        if (!file.read_at(sizes.data(), sizes.size(), e.offset + 4)) continue;
        uint64_t total = 4 + sizes.size();
        for (uint32_t i = 0; i < frames; ++i) total += le32(&sizes[4ull * i]);
        if (total + 5 != e.size) continue;
        uint64_t at = e.offset + 4 + sizes.size();
        for (uint32_t i = 0; i < frames; ++i) {
            uint32_t frame = le32(&sizes[4ull * i]);
            add_source(file, at, frame, out);
            at += frame;
        }
    }
}

int64_t estimate(const std::vector<Source> &sources, int family)
{
    int64_t total = sizeof(tvtx_header);
    for (const Source &s : sources) {
        int64_t blocks = 0;
        for (uint32_t l = 0; l < s.mips; ++l) {
            uint32_t w = s.width >> l ? s.width >> l : 1, h = s.height >> l ? s.height >> l : 1;
            blocks += static_cast<int64_t>((w + 3) / 4) * ((h + 3) / 4);
        }
        /* At most: ETC2 keeps DXT's block sizes (an opaque DXT5 halves); ASTC 4x4 takes 16. */
        total += blocks * s.faces * (family == TVTX_ASTC ? 16 : s.block) + static_cast<int64_t>(sizeof(tvtx_entry));
    }
    return total;
}

/* ------------------------------------------------------------ DXT decode
 * Exactly the port's runtime decode (android/host/d3d9_format.c), so a
 * converted texture starts from the texels the port showed. */

void rgb565(uint32_t c, uint8_t *out)
{
    uint32_t r = (c >> 11) & 31, g = (c >> 5) & 63, b = c & 31;
    out[0] = static_cast<uint8_t>((r << 3) | (r >> 2));
    out[1] = static_cast<uint8_t>((g << 2) | (g >> 4));
    out[2] = static_cast<uint8_t>((b << 3) | (b >> 2));
}

void color_block(const uint8_t *block, uint8_t out[16][4], bool four)
{
    uint32_t c0 = block[0] | (block[1] << 8), c1 = block[2] | (block[3] << 8), bits = le32(block + 4);
    uint8_t pal[4][4];
    rgb565(c0, pal[0]);
    rgb565(c1, pal[1]);
    pal[0][3] = pal[1][3] = 255;
    if (c0 > c1 || four) {
        for (int k = 0; k < 3; ++k) {
            pal[2][k] = static_cast<uint8_t>((2 * pal[0][k] + pal[1][k] + 1) / 3);
            pal[3][k] = static_cast<uint8_t>((pal[0][k] + 2 * pal[1][k] + 1) / 3);
        }
        pal[2][3] = pal[3][3] = 255;
    } else {
        for (int k = 0; k < 3; ++k) pal[2][k] = static_cast<uint8_t>((pal[0][k] + pal[1][k]) / 2);
        pal[2][3] = 255;
        pal[3][0] = pal[3][1] = pal[3][2] = pal[3][3] = 0;
    }
    for (int i = 0; i < 16; ++i) memcpy(out[i], pal[(bits >> (2 * i)) & 3], 4);
}

void alpha_block(const uint8_t *block, uint8_t out[16])
{
    uint32_t a0 = block[0], a1 = block[1];
    uint64_t bits = 0;
    for (int i = 0; i < 6; ++i) bits |= static_cast<uint64_t>(block[2 + i]) << (8 * i);
    uint8_t pal[8];
    pal[0] = static_cast<uint8_t>(a0);
    pal[1] = static_cast<uint8_t>(a1);
    if (a0 > a1) {
        for (uint32_t i = 1; i < 7; ++i) pal[1 + i] = static_cast<uint8_t>(((7 - i) * a0 + i * a1 + 3) / 7);
    } else {
        for (uint32_t i = 1; i < 5; ++i) pal[1 + i] = static_cast<uint8_t>(((5 - i) * a0 + i * a1 + 2) / 5);
        pal[6] = 0;
        pal[7] = 255;
    }
    for (int i = 0; i < 16; ++i) out[i] = pal[(bits >> (3 * i)) & 7];
}

void decode_dxt(uint32_t fourcc, const uint8_t *src, uint32_t width, uint32_t height, uint8_t *rgba)
{
    uint32_t kind = fourcc >> 24, bw = (width + 3) / 4, bh = (height + 3) / 4, step = kind == '1' ? 8 : 16;
    for (uint32_t by = 0; by < bh; ++by)
        for (uint32_t bx = 0; bx < bw; ++bx) {
            const uint8_t *block = src + (static_cast<size_t>(by) * bw + bx) * step;
            uint8_t texels[16][4], alpha[16];
            if (kind == '1') {
                color_block(block, texels, false);
            } else if (kind == '2' || kind == '3') {
                color_block(block + 8, texels, true);
                for (int i = 0; i < 16; ++i) texels[i][3] = static_cast<uint8_t>(((block[i / 2] >> (4 * (i & 1))) & 15) * 17);
            } else {
                color_block(block + 8, texels, true);
                alpha_block(block, alpha);
                for (int i = 0; i < 16; ++i) texels[i][3] = alpha[i];
            }
            for (uint32_t y = 0; y < 4 && by * 4 + y < height; ++y)
                for (uint32_t x = 0; x < 4 && bx * 4 + x < width; ++x)
                    memcpy(rgba + ((static_cast<size_t>(by) * 4 + y) * width + bx * 4 + x) * 4, texels[y * 4 + x], 4);
        }
}

void level_dims(const tvtx_dds &d, uint32_t level, uint32_t &w, uint32_t &h)
{
    w = d.width >> level ? d.width >> level : 1;
    h = d.height >> level ? d.height >> level : 1;
}

uint64_t dxt_level_bytes(const tvtx_dds &d, uint32_t w, uint32_t h)
{
    return static_cast<uint64_t>((w + 3) / 4) * ((h + 3) / 4) * d.block;
}

/* -------------------------------------------------------------- encoders */

struct AstcContext {
    astcenc_context *context[2] = {nullptr, nullptr};   /* opaque, with alpha */
    ~AstcContext() { for (astcenc_context *c : context) if (c) astcenc_context_free(c); }

    astcenc_context *get(bool opaque)
    {
        astcenc_context *&c = context[opaque ? 0 : 1];
        if (c) return c;
        astcenc_config config;
        /* VOID_TEXCONV_ASTC_QUALITY (a development knob): astcenc's quality, 0..100. */
        const char *knob = getenv("VOID_TEXCONV_ASTC_QUALITY");
        float quality = knob ? static_cast<float>(atof(knob)) : ASTCENC_PRE_FAST;
        unsigned flags = opaque ? 0u : ASTCENC_FLG_USE_ALPHA_WEIGHT;
        if (astcenc_config_init(ASTCENC_PRF_LDR, 4, 4, 1, quality, flags, &config) != ASTCENC_SUCCESS) return nullptr;
        if (astcenc_context_alloc(&config, 1, &c, nullptr) != ASTCENC_SUCCESS) c = nullptr;
        return c;
    }
};

thread_local AstcContext astc;

bool encode_level(uint32_t gl_format, const uint8_t *rgba, uint32_t w, uint32_t h, bool opaque, uint8_t *out)
{
    if (gl_format == TVTX_GL_ETC2_RGB8 || gl_format == TVTX_GL_ETC2_RGBA8) {
        /* etcpak: whole 4x4 blocks of BGRA words, rows of the padded width; edges repeat. */
        uint32_t pw = (w + 3) & ~3u, ph = (h + 3) & ~3u;
        std::vector<uint32_t> bgra(static_cast<size_t>(pw) * ph);
        for (uint32_t y = 0; y < ph; ++y)
            for (uint32_t x = 0; x < pw; ++x) {
                const uint8_t *p = rgba + (static_cast<size_t>(std::min(y, h - 1)) * w + std::min(x, w - 1)) * 4;
                bgra[static_cast<size_t>(y) * pw + x] = static_cast<uint32_t>(p[2]) | (static_cast<uint32_t>(p[1]) << 8) |
                                                      (static_cast<uint32_t>(p[0]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
            }
        uint32_t blocks = (pw / 4) * (ph / 4);
        /* etcpak's heuristics choose the T, H and planar modes besides ETC1's: real
         * textures 24..43 dB against 21..42 without them. */
        if (gl_format == TVTX_GL_ETC2_RGB8) CompressEtc2Rgb(bgra.data(), reinterpret_cast<uint64_t *>(out), blocks, pw, true);
        else CompressEtc2Rgba(bgra.data(), reinterpret_cast<uint64_t *>(out), blocks, pw, true);
        return true;
    }
    astcenc_context *context = astc.get(opaque);
    if (!context) return false;
    astcenc_image image{};
    image.dim_x = w;
    image.dim_y = h;
    image.dim_z = 1;
    image.data_type = ASTCENC_TYPE_U8;
    void *slices[] = {const_cast<uint8_t *>(rgba)};
    image.data = slices;
    /* An opaque texture spends no bits on alpha. */
    const astcenc_swizzle swizzle{ASTCENC_SWZ_R, ASTCENC_SWZ_G, ASTCENC_SWZ_B, opaque ? ASTCENC_SWZ_1 : ASTCENC_SWZ_A};
    astcenc_error status = astcenc_compress_image(context, &image, &swizzle, out, tvtx_level_bytes(gl_format, w, h), 0);
    astcenc_compress_reset(context);
    return status == ASTCENC_SUCCESS;
}

/* One DXT DDS into its payload. 0 done, -1 not convertible or the encoder failed. */
int convert_dds(const uint8_t *dds, uint64_t size, int family, std::vector<uint8_t> &payload, uint32_t &gl_format,
                uint32_t &flags)
{
    tvtx_dds d;
    if (!tvtx_dds_bytes(dds, size, &d)) return -1;
    std::vector<std::vector<uint8_t>> levels(static_cast<size_t>(d.faces) * d.mips);
    bool opaque = true;
    const uint8_t *src = dds + 128;
    for (uint32_t f = 0; f < d.faces; ++f)
        for (uint32_t l = 0; l < d.mips; ++l) {
            uint32_t w, h;
            level_dims(d, l, w, h);
            std::vector<uint8_t> &level = levels[static_cast<size_t>(f) * d.mips + l];
            level.resize(static_cast<size_t>(w) * h * 4);
            decode_dxt(d.fourcc, src, w, h, level.data());
            src += dxt_level_bytes(d, w, h);
            for (size_t i = 3; i < level.size() && opaque; i += 4) opaque = level[i] == 255;
        }
    gl_format = family == TVTX_ASTC ? TVTX_GL_ASTC_4x4 : opaque ? TVTX_GL_ETC2_RGB8 : TVTX_GL_ETC2_RGBA8;
    flags = opaque ? TVTX_OPAQUE : 0u;
    uint64_t total = 0;
    for (uint32_t l = 0; l < d.mips; ++l) {
        uint32_t w, h;
        level_dims(d, l, w, h);
        total += tvtx_level_bytes(gl_format, w, h);
    }
    payload.assign(static_cast<size_t>(total * d.faces), 0);
    uint8_t *dst = payload.data();
    for (uint32_t f = 0; f < d.faces; ++f)
        for (uint32_t l = 0; l < d.mips; ++l) {
            uint32_t w, h;
            level_dims(d, l, w, h);
            if (!encode_level(gl_format, levels[static_cast<size_t>(f) * d.mips + l].data(), w, h, opaque, dst)) return -1;
            dst += tvtx_level_bytes(gl_format, w, h);
        }
    return 0;
}

tvtx_crc_tables crc_tables;

uint64_t key_of(const uint8_t *data, size_t n)
{
    static std::once_flag once;
    std::call_once(once, [] { tvtx_crc_init(&crc_tables); });
    return tvtx_key(&crc_tables, data, n);
}

/* ------------------------------------------------------------ the pack */

bool read_pack_header(const std::string &path, tvtx_header &h, uint64_t &file_size)
{
    File f;
    if (!f.open_read(path)) return false;
    file_size = f.size();
    if (file_size < sizeof h || !f.read_at(&h, sizeof h, 0)) return false;
    return h.magic == TVTX_MAGIC && h.version == TVTX_VERSION && (h.family == TVTX_ETC2 || h.family == TVTX_ASTC) &&
           h.index_offset + static_cast<uint64_t>(h.count) * sizeof(tvtx_entry) == file_size;
}

struct Inventory {
    File container;
    uint64_t container_size = 0;
    std::vector<Source> sources;
    int64_t bytes = 0;
};

int inventory(const char *game, Inventory &inv)
{
    std::string path = data_dir(game) + "/Textures.vfs";
    if (!inv.container.open_read(path)) return fail("cannot open %s", path.c_str());
    inv.container_size = inv.container.size();
    std::vector<Entry> entries;
    if (!read_container(inv.container, entries)) return fail("%s: not a readable LP2C container", path.c_str());
    collect_sources(inv.container, entries, inv.sources);
    for (const Source &s : inv.sources) inv.bytes += s.bytes;
    return 0;
}

}  // namespace

/* =============================================================== the API */

extern "C" int texconv_scan(const char *game_dir, texconv_status *out)
{
    *out = texconv_status{};
    Inventory inv;
    if (inventory(game_dir, inv)) return -1;
    out->textures = static_cast<int64_t>(inv.sources.size());
    out->bytes = inv.bytes;
    out->estimate_etc2 = estimate(inv.sources, TVTX_ETC2);
    out->estimate_astc = estimate(inv.sources, TVTX_ASTC);
    out->free_bytes = free_space(data_dir(game_dir));
    tvtx_header h;
    uint64_t size = 0;
    if (read_pack_header(pack_path(game_dir), h, size)) {
        out->converted = static_cast<int>(h.family);
        out->converted_textures = h.count;
        out->converted_bytes = static_cast<int64_t>(size);
        out->current = h.source_container == inv.container_size && h.sources == inv.sources.size();
    }
    return 0;
}

extern "C" int texconv_convert(const char *game_dir, int family, int threads)
{
    cancelled = false;
    begin(TEXCONV_SCANNING, 0, 0);
    if (family != TVTX_ETC2 && family != TVTX_ASTC) return fail("unknown format %d", family);
    Inventory inv;
    if (inventory(game_dir, inv)) return -1;
    if (inv.sources.empty()) return fail("no DXT textures in data/Textures.vfs");
    std::string final_path = pack_path(game_dir), part = final_path + ".part";
    int64_t need = estimate(inv.sources, family), room = free_space(data_dir(game_dir));
    /* A pack being replaced frees its space only at the end. */
    if (room >= 0 && room < need + (64 << 20)) {
        return fail("not enough space: %lld MB needed, %lld MB free", static_cast<long long>(need >> 20),
                    static_cast<long long>(room >> 20));
    }
    File out;
    if (!out.create(part)) return fail("cannot create %s", part.c_str());
    begin(TEXCONV_CONVERTING, static_cast<int64_t>(inv.sources.size()), inv.bytes);
    if (threads <= 0) threads = static_cast<int>(std::thread::hardware_concurrency());
    threads = std::max(1, std::min(threads, 16));

    std::mutex write_lock;
    uint64_t write_at = sizeof(tvtx_header);
    std::vector<tvtx_entry> index;
    index.reserve(inv.sources.size());
    std::atomic<size_t> next{0};
    std::atomic<bool> broken{false};
    std::string why;
    uint32_t skipped = 0;
    auto worker = [&]() {
        std::vector<uint8_t> dds, payload;
        for (;;) {
            if (cancelled || broken) return;
            size_t i = next++;
            if (i >= inv.sources.size()) return;
            const Source &s = inv.sources[i];
            dds.resize(s.bytes);
            uint32_t gl_format = 0, flags = 0;
            bool ok = inv.container.read_at(dds.data(), s.bytes, s.offset);
            if (!ok) {
                std::lock_guard<std::mutex> lock(write_lock);
                if (!broken.exchange(true)) why = "cannot read data/Textures.vfs";
                return;
            }
            uint64_t key = key_of(dds.data(), s.bytes);
            int converted = convert_dds(dds.data(), s.bytes, family, payload, gl_format, flags);
            {
                std::lock_guard<std::mutex> lock(write_lock);
                bool duplicate = false;
                for (const tvtx_entry &e : index) if (e.key == key && e.dds_bytes == s.bytes) { duplicate = true; break; }
                if (converted != 0 || duplicate) {
                    ++skipped;
                } else {
                    if (!out.write_at(payload.data(), payload.size(), write_at)) {
                        if (!broken.exchange(true)) why = "cannot write the converted textures (is the storage full?)";
                        return;
                    }
                    index.push_back(tvtx_entry{key, s.bytes, gl_format, write_at, static_cast<uint32_t>(payload.size()), flags});
                    write_at += payload.size();
                }
            }
            ++done_textures;
            done_bytes += s.bytes;
        }
    };
    std::vector<std::thread> pool;
    for (int t = 0; t < threads; ++t) pool.emplace_back(worker);
    for (std::thread &t : pool) t.join();
    if (cancelled || broken) {
        out.close();
        remove_file(part);
        if (cancelled) {
            set_state(TEXCONV_CANCELLED);
            return -1;
        }
        return fail("%s", why.c_str());
    }
    set_state(TEXCONV_FINISHING);
    std::sort(index.begin(), index.end(), [](const tvtx_entry &a, const tvtx_entry &b) {
        return a.key != b.key ? a.key < b.key : a.dds_bytes < b.dds_bytes;
    });
    tvtx_header h{};
    h.magic = TVTX_MAGIC;
    h.version = TVTX_VERSION;
    h.family = static_cast<uint32_t>(family);
    h.count = static_cast<uint32_t>(index.size());
    h.index_offset = write_at;
    h.payload_bytes = write_at - sizeof h;
    h.source_bytes = static_cast<uint64_t>(inv.bytes);
    h.source_container = inv.container_size;
    h.sources = static_cast<uint32_t>(inv.sources.size());
    h.skipped = skipped;
    bool ok = out.write_at(index.data(), index.size() * sizeof(tvtx_entry), write_at) && out.write_at(&h, sizeof h, 0) &&
              out.sync() && out.close();
    if (!ok || !replace_file(part, final_path)) {
        out.close();
        remove_file(part);
        return fail("cannot finish %s", final_path.c_str());
    }
    {
        std::lock_guard<std::mutex> lock(progress_lock);
        progress_state.done = progress_state.total = static_cast<int64_t>(inv.sources.size());
        progress_state.bytes_done = progress_state.bytes_total = inv.bytes;
        progress_state.state = TEXCONV_DONE;
    }
    return 0;
}

extern "C" int texconv_remove(const char *game_dir)
{
    std::string path = pack_path(game_dir);
    bool ok = remove_file(path + ".part") && remove_file(path);
    if (!ok) return fail("cannot delete %s", path.c_str());
    return exists(path) ? fail("%s is still there", path.c_str()) : 0;
}

extern "C" void texconv_cancel(void) { cancelled = true; }

extern "C" void texconv_get_progress(texconv_progress *out)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    *out = progress_state;
    if (out->state == TEXCONV_CONVERTING) {
        out->done = done_textures;
        out->bytes_done = done_bytes;
    }
}

extern "C" int texconv_convert_dds(const uint8_t *dds, uint64_t size, int family, uint8_t **out, uint64_t *out_size,
    uint32_t *gl_format, uint32_t *flags)
{
    std::vector<uint8_t> payload;
    if (convert_dds(dds, size, family, payload, *gl_format, *flags)) return -1;
    *out = static_cast<uint8_t *>(malloc(payload.size() ? payload.size() : 1));
    if (!*out) return -1;
    memcpy(*out, payload.data(), payload.size());
    *out_size = payload.size();
    return 0;
}

extern "C" void texconv_free(void *pointer) { free(pointer); }

extern "C" int texconv_decode_dxt(const uint8_t *dds, uint64_t size, uint32_t face, uint32_t level, uint8_t *rgba)
{
    tvtx_dds d;
    if (!tvtx_dds_bytes(dds, size, &d) || face >= d.faces || level >= d.mips) return -1;
    const uint8_t *src = dds + 128;
    for (uint32_t f = 0; f <= face; ++f)
        for (uint32_t l = 0; l < d.mips; ++l) {
            uint32_t w, h;
            level_dims(d, l, w, h);
            if (f == face && l == level) {
                decode_dxt(d.fourcc, src, w, h, rgba);
                return 0;
            }
            src += dxt_level_bytes(d, w, h);
        }
    return -1;
}

extern "C" int texconv_decode_converted(uint32_t gl_format, const uint8_t *blocks, uint32_t w, uint32_t h, uint8_t *rgba)
{
    if (gl_format == TVTX_GL_ETC2_RGB8 || gl_format == TVTX_GL_ETC2_RGBA8) {
        uint32_t pw = (w + 3) & ~3u, ph = (h + 3) & ~3u;
        std::vector<uint32_t> decoded(static_cast<size_t>(pw) * ph);   /* RGBA words */
        std::vector<uint64_t> words(tvtx_level_bytes(gl_format, w, h) / 8);
        memcpy(words.data(), blocks, words.size() * 8);
        if (gl_format == TVTX_GL_ETC2_RGB8) DecodeRGB(words.data(), decoded.data(), static_cast<int32_t>(pw), static_cast<int32_t>(ph));
        else DecodeRGBA(words.data(), decoded.data(), static_cast<int32_t>(pw), static_cast<int32_t>(ph));
        for (uint32_t y = 0; y < h; ++y)
            for (uint32_t x = 0; x < w; ++x) {
                uint32_t v = decoded[static_cast<size_t>(y) * pw + x];
                uint8_t *p = rgba + (static_cast<size_t>(y) * w + x) * 4;
                p[0] = static_cast<uint8_t>(v);
                p[1] = static_cast<uint8_t>(v >> 8);
                p[2] = static_cast<uint8_t>(v >> 16);
                p[3] = gl_format == TVTX_GL_ETC2_RGB8 ? 255 : static_cast<uint8_t>(v >> 24);
            }
        return 0;
    }
    if (gl_format != TVTX_GL_ASTC_4x4) return -1;
    astcenc_context *context = astc.get(false);
    if (!context) return -1;
    astcenc_image image{};
    image.dim_x = w;
    image.dim_y = h;
    image.dim_z = 1;
    image.data_type = ASTCENC_TYPE_U8;
    void *slices[] = {rgba};
    image.data = slices;
    const astcenc_swizzle swizzle{ASTCENC_SWZ_R, ASTCENC_SWZ_G, ASTCENC_SWZ_B, ASTCENC_SWZ_A};
    astcenc_error status = astcenc_decompress_image(context, blocks, tvtx_level_bytes(gl_format, w, h), &image, &swizzle, 0);
    astcenc_decompress_reset(context);
    return status == ASTCENC_SUCCESS ? 0 : -1;
}

extern "C" uint64_t texconv_key(const uint8_t *data, uint64_t size) { return key_of(data, static_cast<size_t>(size)); }
