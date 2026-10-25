/* Game sounds the touch layer vibrates to (sound_events.c). */
#ifndef VOID_SOUND_EVENTS_H
#define VOID_SOUND_EVENTS_H
#include <stdint.h>

enum { SOUND_EVENT_LAND, SOUND_EVENT_DAMAGE, SOUND_EVENT_ABSORB, SOUND_EVENTS };

/* The event a static sound buffer of this many bytes plays, or -1. */
int void_sound_event_for_size(uint32_t bytes);
/* A buffer with an event started playing. */
void void_sound_event_played(int event);
/* How many times each event has played since the start. */
void void_sound_events(uint32_t out[SOUND_EVENTS]);
/* How many buffers of the event are playing now (dsound.c). */
int void_sound_event_playing(int event);
/* Testing the layer's vibration (script.c "sound"): playing < 0 counts the
 * event once, as if its sound started; otherwise that many buffers of it
 * count as playing until changed. */
void void_sound_event_force(int event, int playing);
int void_sound_event_forced(int event);

#endif
