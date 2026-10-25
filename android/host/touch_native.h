#ifndef VOID_TOUCH_NATIVE_H
#define VOID_TOUCH_NATIVE_H
#include <stdint.h>

void void_touch_movement(float x, float y);
void void_touch_gameplay_options(float fov, float veins);
void void_touch_observe_context(uint32_t context);
int void_touch_console(const char *command);
void void_touch_commands_pump(void);
int void_touch_body_target(void);
int void_touch_body_transfer_colour(void);
void void_touch_body_target_reset(void);
void void_touch_body_amounts(float out[28]);
void void_touch_body_details(float out[14]);
void void_touch_body_stat_name(int colour, char out[256]);
int void_touch_zone_labels(float out[21 * 5]);
int void_touch_hint_texts(char out[56][256]);
int void_touch_brush_colour(void);
void void_touch_cancel_stroke(void);
void void_touch_harvest_begin(void);
void void_touch_harvest_stop(void);
int void_touch_harvest_blocked(void);

#endif
