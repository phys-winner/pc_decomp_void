#ifndef VOID_SETTINGS_REGEX_H
#define VOID_SETTINGS_REGEX_H
#ifdef __cplusplus
extern "C" {
#endif
/* Exact shipped Search expression, with the original added end anchor.
 * 1 matches, 0 does not, -1 invalid expression (original catches/skips it). */
int void_settings_regex_match(const char *pattern, const char *description);
#ifdef __cplusplus
}
#endif
#endif
