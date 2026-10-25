"""Exercise shipping FF uniform-cache cleanup when GL reuses program names."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    ff = (ROOT / "android/host/d3d9_ff.c").read_text()
    shader = (ROOT / "android/host/d3d9_shader.c").read_text()

    def function(source, name):
        return re.search(r"^(?:static )?(?:void|ff_locs \*) ?" + name
                         + r"\([^\n]*\)\n\{.*?^\}", source, re.M | re.S).group()

    declarations = re.search(r"typedef struct ff_locs \{.*?\} ff_locs;", ff, re.S).group()
    functions = "\n".join([function(ff, "locations"), function(ff, "d3d_ff_forget_program"),
                            function(shader, "forget_programs")])
    source = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned GLuint;
typedef int GLint;
typedef struct { int unused; } d3d_shader;
typedef struct program {
    d3d_shader *vs, *ps;
    GLuint gl;
    void *vs_f, *ps_f, *vs_i, *ps_i, *vs_b, *ps_b, *vs_f_loc, *ps_f_loc;
    struct program *next;
} program_t;
static program_t *programs[1024], *current_program;
static d3d_shader *failed_vs, *failed_ps;
static uint64_t failed_program;
static int generation, queries, deleted, stale_at_delete;
static GLint glGetUniformLocation(GLuint program, const char *name) {
    unsigned hash = program;
    for (; *name; ++name) hash = hash * 33u + (unsigned char)*name;
    ++queries;
    return generation * 1024 + (GLint)(hash & 511);
}
static void glUniform1i(GLint loc, int value) { (void)loc; (void)value; }
'''
    source += declarations + "\nstatic ff_locs *locs_table[64];\n"
    source += r'''
static void glDeleteProgram(GLuint program) {
    ++deleted;
    for (ff_locs *l = locs_table[program & 63]; l; l = l->next)
        if (l->program == program) ++stale_at_delete;
}
'''
    source += functions + r'''
#define CHECK(x) do { if (!(x)) { printf("failed line %d: %s\n", __LINE__, #x); return 1; } } while (0)
int main(void) {
    d3d_shader owner = {0}, other = {0};
    ff_locs *survivor = locations(7);
    locations(71); locations(135); /* Same hash bucket; remove its middle and head. */
    int before = queries;
    CHECK(locations(7) == survivor && queries == before);
    d3d_ff_forget_program(999); /* Absent entry is harmless. */
    for (int i = 0; i < 500; ++i) {
        program_t *p = calloc(1, sizeof *p), *q = calloc(1, sizeof *q);
        CHECK(p && q);
        p->vs = &owner; p->gl = 71; p->next = q;
        q->ps = &owner; q->gl = 135;
        programs[19] = current_program = p;
        forget_programs(&other); /* No matching program: keep all cache entries. */
        CHECK(programs[19] == p && current_program == p);
        failed_vs = &owner; failed_ps = &other; failed_program = 123;
        forget_programs(&owner);
        CHECK(!programs[19] && !current_program && !failed_program);
        CHECK(!failed_vs && !failed_ps && !stale_at_delete);
        ++generation; /* Driver reuses 71/135, but uniform locations have changed. */
        CHECK(locations(71)->vp == glGetUniformLocation(71, "ff_vp"));
        CHECK(locations(135)->half == glGetUniformLocation(135, "ff_half"));
        before = queries;
        CHECK(locations(7) == survivor && queries == before);
    }
    CHECK(deleted == 1000);
    d3d_ff_forget_program(7); d3d_ff_forget_program(71); d3d_ff_forget_program(135);
    CHECK(!locs_table[7]);
    puts("PASS: 1000 program deletions/name reuses; collision chain and live cache preserved");
    return 0;
}
'''
    out = ROOT / "build/ff-program-lifetime-test"
    out.mkdir(parents=True, exist_ok=True)
    compiler, env, _ = compiler_environment()
    for label, text in [("original", source.replace("            d3d_ff_forget_program(p->gl);", "")),
                        ("fixed", source)]:
        c = out / (label + ".c")
        c.write_text(text)
        exe = out / (label + ".exe")
        subprocess.run([str(compiler), "/nologo", "/W4", "/WX", "/O2", "/std:c11",
                        str(c), "/Fo" + str(out / (label + ".obj")), "/Fe" + str(exe)],
                       env=env, capture_output=True, text=True, check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        (out / (label + ".log")).write_text(run.stdout + run.stderr)
        assert (run.returncode == 0) == (label == "fixed"), run.stdout + run.stderr
        print(label + ": " + run.stdout.strip())


if __name__ == "__main__":
    main()
