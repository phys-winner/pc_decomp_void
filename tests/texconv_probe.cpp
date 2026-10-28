// PC driver of android/texconv for tests/test_texconv.py.
//   texconv_probe scan <game>
//   texconv_probe convert <game> etc2|astc [threads]
//   texconv_probe remove <game>
//   texconv_probe key <file> [bytes]               the tvtx key of a file's first bytes
//   texconv_probe check <game> <floor dB> <dds>... every DDS found in the pack, every level decodes above the PSNR floor
//   texconv_probe quality etc2|astc <dds>...        level-0 PSNR against the DXT decode and the time per texture
#include "../android/texconv/texconv.h"
#include "../android/texconv/tvtx.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

static std::vector<uint8_t> load(const char *path)
{
    std::vector<uint8_t> data;
    FILE *f = fopen(path, "rb");
    if (!f) return data;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    data.resize(static_cast<size_t>(size));
    if (size && fread(data.data(), 1, data.size(), f) != data.size()) data.clear();
    fclose(f);
    return data;
}

static int report(int result)
{
    texconv_progress p;
    texconv_get_progress(&p);
    printf("result %d state %d done %lld/%lld bytes %lld/%lld message \"%s\"\n", result, p.state, static_cast<long long>(p.done),
           static_cast<long long>(p.total), static_cast<long long>(p.bytes_done), static_cast<long long>(p.bytes_total), p.message);
    return result == 0 ? 0 : 2;
}

static void psnr(const std::vector<uint8_t> &a, const std::vector<uint8_t> &b, double &rgb, double &alpha)
{
    double se_rgb = 0, se_a = 0;
    size_t n = a.size() / 4;
    for (size_t i = 0; i < n; ++i) {
        for (int c = 0; c < 3; ++c) { double d = double(a[i * 4 + c]) - b[i * 4 + c]; se_rgb += d * d; }
        double d = double(a[i * 4 + 3]) - b[i * 4 + 3];
        se_a += d * d;
    }
    double mse_rgb = se_rgb / (n * 3.0), mse_a = se_a / n;
    rgb = mse_rgb > 0 ? 10 * log10(255.0 * 255.0 / mse_rgb) : 99;
    alpha = mse_a > 0 ? 10 * log10(255.0 * 255.0 / mse_a) : 99;
}

static int family_of(const char *name) { return !strcmp(name, "astc") ? TVTX_ASTC : !strcmp(name, "etc2") ? TVTX_ETC2 : 0; }

/* Every level of every face of a DDS against its converted payload. */
static bool compare(const std::vector<uint8_t> &dds, uint32_t gl_format, const uint8_t *payload, uint64_t payload_bytes,
                    double floor, const char *name)
{
    tvtx_dds d;
    if (!tvtx_dds_bytes(dds.data(), dds.size(), &d)) return false;
    uint64_t at = 0;
    for (uint32_t f = 0; f < d.faces; ++f)
        for (uint32_t l = 0; l < d.mips; ++l) {
            uint32_t w = d.width >> l ? d.width >> l : 1, h = d.height >> l ? d.height >> l : 1;
            uint64_t bytes = tvtx_level_bytes(gl_format, w, h);
            if (at + bytes > payload_bytes) { printf("%s: payload too short at face %u level %u\n", name, f, l); return false; }
            std::vector<uint8_t> reference(static_cast<size_t>(w) * h * 4), converted(reference.size());
            if (texconv_decode_dxt(dds.data(), dds.size(), f, l, reference.data()) ||
                texconv_decode_converted(gl_format, payload + at, w, h, converted.data())) {
                printf("%s: decode failed at face %u level %u\n", name, f, l);
                return false;
            }
            double rgb, alpha;
            psnr(reference, converted, rgb, alpha);
            /* The levels at 4x4 and below carry too few texels for a stable PSNR. */
            if ((w >= 8 || h >= 8) && (rgb < floor || alpha < floor)) {
                printf("%s: face %u level %u %ux%u PSNR rgb %.2f alpha %.2f below %.1f\n", name, f, l, w, h, rgb, alpha, floor);
                return false;
            }
            at += bytes;
        }
    if (at != payload_bytes) { printf("%s: payload %llu bytes, levels %llu\n", name, (unsigned long long)payload_bytes, (unsigned long long)at); return false; }
    return true;
}

int main(int argc, char **argv)
{
    if (argc < 2) return 1;
    std::string cmd = argv[1];
    if (cmd == "scan" && argc == 3) {
        texconv_status s;
        int r = texconv_scan(argv[2], &s);
        printf("scan textures %lld bytes %lld etc2 %lld astc %lld converted %d %lld %lld current %d\n",
               static_cast<long long>(s.textures), static_cast<long long>(s.bytes), static_cast<long long>(s.estimate_etc2),
               static_cast<long long>(s.estimate_astc), s.converted, static_cast<long long>(s.converted_textures),
               static_cast<long long>(s.converted_bytes), s.current);
        return report(r);
    }
    if (cmd == "convert" && argc >= 4) {
        int family = family_of(argv[3]);
        auto start = std::chrono::steady_clock::now();
        int r = texconv_convert(argv[2], family, argc > 4 ? atoi(argv[4]) : 0);
        double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        printf("seconds %.2f\n", seconds);
        return report(r);
    }
    if (cmd == "remove" && argc == 3) return report(texconv_remove(argv[2]));
    if (cmd == "key" && argc >= 3) {
        std::vector<uint8_t> data = load(argv[2]);
        size_t n = argc > 3 ? static_cast<size_t>(strtoull(argv[3], nullptr, 10)) : data.size();
        if (n > data.size()) return 1;
        printf("key %016llx\n", static_cast<unsigned long long>(texconv_key(data.data(), n)));
        return 0;
    }
    if (cmd == "check" && argc >= 5) {
        std::string path = std::string(argv[2]) + "/data/" TVTX_FILE;
        std::vector<uint8_t> pack = load(path.c_str());
        if (pack.size() < sizeof(tvtx_header)) { printf("no pack\n"); return 2; }
        tvtx_header h;
        memcpy(&h, pack.data(), sizeof h);
        if (h.magic != TVTX_MAGIC || h.index_offset + uint64_t(h.count) * sizeof(tvtx_entry) != pack.size()) { printf("bad pack\n"); return 2; }
        const tvtx_entry *index = reinterpret_cast<const tvtx_entry *>(pack.data() + h.index_offset);
        double floor = atof(argv[3]);
        int missing = 0, bad = 0;
        for (int i = 4; i < argc; ++i) {
            std::vector<uint8_t> dds = load(argv[i]);
            tvtx_dds d;
            uint64_t bytes = tvtx_dds_bytes(dds.data(), dds.size(), &d);
            const tvtx_entry *e = bytes ? tvtx_find(index, h.count, texconv_key(dds.data(), bytes), static_cast<uint32_t>(bytes)) : nullptr;
            if (!e) { ++missing; printf("missing %s\n", argv[i]); continue; }
            std::vector<uint8_t> source(dds.begin(), dds.begin() + static_cast<long long>(bytes));
            if (!compare(source, e->gl_format, pack.data() + e->offset, e->bytes, floor, argv[i])) ++bad;
        }
        printf("check family %u entries %u missing %d bad %d\n", h.family, h.count, missing, bad);
        return missing || bad ? 2 : 0;
    }
    if (cmd == "quality" && argc >= 4) {
        int family = family_of(argv[2]);
        double worst = 99, ms = 0;
        for (int i = 3; i < argc; ++i) {
            std::vector<uint8_t> dds = load(argv[i]);
            uint8_t *payload = nullptr;
            uint64_t bytes = 0;
            uint32_t gl_format = 0, flags = 0;
            auto start = std::chrono::steady_clock::now();
            if (texconv_convert_dds(dds.data(), dds.size(), family, &payload, &bytes, &gl_format, &flags)) { printf("not convertible %s\n", argv[i]); return 2; }
            ms += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
            tvtx_dds d;
            tvtx_dds_bytes(dds.data(), dds.size(), &d);
            std::vector<uint8_t> reference(static_cast<size_t>(d.width) * d.height * 4), converted(reference.size());
            texconv_decode_dxt(dds.data(), dds.size(), 0, 0, reference.data());
            texconv_decode_converted(gl_format, payload, d.width, d.height, converted.data());
            double rgb, alpha;
            psnr(reference, converted, rgb, alpha);
            printf("%s %ux%u %04x flags %u rgb %.2f alpha %.2f\n", argv[i], d.width, d.height, gl_format, flags, rgb, alpha);
            worst = std::min(worst, std::min(rgb, alpha));
            texconv_free(payload);
        }
        printf("quality worst %.2f ms %.1f\n", worst, ms);
        return 0;
    }
    return 1;
}
