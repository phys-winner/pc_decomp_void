/* The interface scale for the game's text (fonts.c). */
#ifndef VOID_FONTS_H
#define VOID_FONTS_H

/* Text size factor: the touch layer's interface scale at the render size. */
void void_fonts_set_scale(float scale);
/* The host file that serves the font a normalized game path names
 * (C:\Games\The Void\data\Textures\...\fontmain_<px>.ft) at the scale, or
 * NULL when the game's own file serves (malloc'd). */
char *void_fonts_path(const char *norm);

#endif
