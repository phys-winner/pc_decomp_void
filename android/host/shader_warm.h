#ifndef VOID_SHADER_WARM_H
#define VOID_SHADER_WARM_H
#include <GLES3/gl32.h>
#include <stdint.h>

GLuint d3d_shader_compile_source(GLenum type, const char *source);
const char *d3d_shader_source_for(GLuint shader);
int d3d_shader_warm_bytecode(const void *bytes, uint32_t size);
GLuint d3d_warm_program(GLuint vs, GLuint ps, int count, const char *const *names);
void d3d_shader_warm_step(void);
uint64_t d3d_shader_warm_progress(void);
void d3d_shader_warm_stats(void);
const char *void_d3dx_packaged_cache_dir(void);
#endif
