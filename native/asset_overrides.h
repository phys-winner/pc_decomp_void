#pragma once
#include <windows.h>

/* Call once before game threads. CommonAppData must match VOID_PROFILE_ROOT.
 * Settings read/save uses its seeded private file; originals stay unchanged. */
BOOL void_asset_overrides_init(LPCWSTR original_data_directory,
                              LPCWSTR runtime_assets_root,
                              LPCSTR expected_main_menu_sha256_hex,
                              LPCWSTR profile_common);
HANDLE WINAPI void_asset_create_file_w(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES,
                                      DWORD, DWORD, HANDLE);
HANDLE WINAPI void_asset_create_file_a(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES,
                                      DWORD, DWORD, HANDLE);
DWORD WINAPI void_asset_get_file_attributes_w(LPCWSTR);
DWORD WINAPI void_asset_get_file_attributes_a(LPCSTR);
LONG void_asset_overrides_script_open_count(void);
