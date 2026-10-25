/* Reading a VFS container's directory (vfs_dir.c). */
#ifndef VOID_VFS_DIR_H
#define VOID_VFS_DIR_H
#include <stdint.h>
#include <stdio.h>

/* path: "<root>\dir\file.ext" as the container stores it; offset and size
 * of the file's bytes in the container. */
typedef void (*void_vfs_entry_fn)(const char *path, uint32_t offset, uint32_t size, void *ctx);

/* The release's data/<container> (case-insensitive name), or NULL. */
FILE *void_vfs_open(const char *container);
/* Calls fn for every file; returns 0 if the directory is unreadable. */
int void_vfs_scan(FILE *f, const char *root, void_vfs_entry_fn fn, void *ctx);

#endif
