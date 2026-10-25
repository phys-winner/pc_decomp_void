#ifndef VOID_SETTINGS_DEBUG_H
#define VOID_SETTINGS_DEBUG_H
#include <wchar.h>

/* Pinned original data directory; read-only profiles.xml. Call before init. */
int void_settings_debug_set_data_directory(const wchar_t *original_data);

/* common_appdata must be VOID_PROFILE_ROOT/CommonAppData, not the real global
 * directory. Returns 1 on success. Renderer/audio changes apply next launch. */
int void_settings_debug_init(const wchar_t *common_appdata);

/* 0: unrelated command, 1: committed, -1: recognized but rejected/failed.
 * Called only on the serialized game/UI thread; no independent input thread. */
int void_settings_debug_command(const wchar_t *command);
const char *void_settings_debug_error(void);

/* Current numeric port properties, including dynamic adapter metadata. At most
 * 15 entries; static key pointers remain valid. Returns entries written. */
unsigned void_settings_debug_snapshot(const wchar_t **keys, int *values, unsigned capacity);

#ifdef VOID_SETTINGS_TEST
void void_settings_debug_test_adapter(unsigned vendor,unsigned device,const char *description,
    const int *mode_triples,unsigned count,unsigned aa_mask,unsigned hdr_aa_mask,unsigned maximum_af);
#endif

#endif
