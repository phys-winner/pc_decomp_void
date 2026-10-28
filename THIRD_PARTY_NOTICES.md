# Third-party notices

The port's own code and documentation are GPL-3.0-or-later as stated in
readme.md. The following components and derived portions retain their original
licenses and attribution. These notices do not license original game code or
resources. Full upstream notices also remain in each dependency checkout.

## pcrecomp — MIT

Source: https://github.com/sp00nznet/pcrecomp

Pinned revision: `904ac3129d0c9d05efbeec19a1dce6abbe7f5d26`.

The pinned recompilation tools and portions of the lifting/runtime support are derived from pcrecomp. Project additions are GPL-3.0-or-later; retain the MIT notice for upstream portions.

```text
MIT License

Copyright (c) 2026 sp00nz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---------------------------------------------------------------------------
Scope

This repository is tools only. Every file in it is original work: the
analysers, lifters, runtimes, Ghidra/IDA scripts and documentation. No
third-party source is vendored here. capstone (BSD-3-Clause), pefile (MIT),
Ghidra (Apache-2.0) and IDA are used as libraries or hosts, under their own
licences, and are not redistributed by this repository.

The MIT grant above therefore applies cleanly to everything here.

What it does not do is give you rights to the software you point these tools
at. Lifting a binary produces a derivative work of that binary: the output is
covered by whatever licence the original carries, not by this one. Own what you
take apart, and do not redistribute other people's executables, data or assets
because a tool in here could read them.
```

## MojoShader — zlib

Source: https://github.com/icculus/mojoshader

Pinned revision: `cf2661bcb55d9a8732e86f79922592d7efdf5383`.

Used by the D3D9 shader host. The build adjusts pixel-shader DCL semantics in its private assembler copy; the fetched checkout is unchanged.

```text
Copyright (c) 2008-2024 Ryan C. Gordon <icculus@icculus.org>

This software is provided 'as-is', without any express or implied
warranty.  In no event will the authors be held liable for any damages
arising from the use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not
   claim that you wrote the original software. If you use this software
   in a product, an acknowledgment in the product documentation would be
   appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
```

## stb — MIT or public domain

Source: https://github.com/nothings/stb

Pinned revision: `2c980bb59875b0d32144a71867fbdebb2f77cd20`.

stb_vorbis.c (v1.22) and stb_image_write.h (v1.16) are used by the native sound decoder and screenshot writer.

```text
This software is available under 2 licenses -- choose whichever you prefer.
------------------------------------------------------------------------------
ALTERNATIVE A - MIT License
Copyright (c) 2017 Sean Barrett
Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
------------------------------------------------------------------------------
ALTERNATIVE B - Public Domain (www.unlicense.org)
This is free and unencumbered software released into the public domain.
Anyone is free to copy, modify, publish, use, compile, sell, or distribute this
software, either in source code form or as a compiled binary, for any purpose,
commercial or non-commercial, and by any means.
In jurisdictions that recognize copyright laws, the author or authors of this
software dedicate any and all copyright interest in the software to the public
domain. We make this dedication for the benefit of the public at large and to
the detriment of our heirs and successors. We intend this dedication to be an
overt act of relinquishment in perpetuity of all present and future rights to
this software under copyright law.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## XZ Embedded — 0BSD

Source: https://github.com/tukaani-project/xz-embedded

Pinned revision: `ae63ae3a36ed01724674e8f3d750dc47bf125410`.

Used by android/unpack/unpack.c to unpack the XZ-compressed native libraries.

```text
Copyright (C) The XZ Embedded authors and contributors

Permission to use, copy, modify, and/or distribute this
software for any purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL
WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL
THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR
CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

## libtheora 1.0 — BSD-3-Clause

Source: https://gitlab.xiph.org/xiph/theora

Pinned revision: `1bcbdce04664d96dfa280f259d4291b871e4cffe`.

Used by android/host/theora_native.c; lib/dec/idct.c is included from the pinned source checkout.

```text
Copyright (C) 2002-2008 Xiph.Org Foundation and contributors.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

- Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

- Neither the name of the Xiph.Org Foundation nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE FOUNDATION
OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## libtheora patent statement

```text
Please see the file COPYING for the copyright license for this software.

In addition to and irrespective of the copyright license associated
with this software, On2 Technologies, Inc. makes the following statement
regarding technology used in this software:

  On2 represents and warrants that it shall not assert any rights
  relating to infringement of On2's registered patents, nor initiate
  any litigation asserting such rights, against any person who, or
  entity which utilizes the On2 VP3 Codec Software, including any
  use, distribution, and sale of said Software; which make changes,
  modifications, and improvements in said Software; and to use,
  distribute, and sell said changes as well as applications for other
  fields of use.

This reference implementation is originally derived from the On2 VP3
Codec Software, and the Theora video format is essentially compatible
with the VP3 video format, consisting of a backward-compatible superset.
```

## dlmalloc 2.8.6 — MIT-0

Source: https://gee.cs.oswego.edu/pub/misc/malloc.c

Vendored file: `reference/dlmalloc/malloc.c`. Copyright 2023 Doug Lea.
The source was relicensed from CC0 to MIT-0 on 25 September 2023.

```text
Copyright 2023 Doug Lea

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## libvorbis — BSD-3-Clause

Source: https://github.com/xiph/vorbis

The MDCT algorithm adapted in `android/host/sound_native.c` derives from
libvorbis `lib/mdct.c`. Preserve the Xiph notice for these portions.

```text
Copyright (c) 2002-2004 Xiph.org Foundation

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

- Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

- Neither the name of the Xiph.org Foundation nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE FOUNDATION
OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## The Void Extractor — GPL-3.0-or-later

Source: https://github.com/Grumbel/thevoid-extractor

Reference revision: `cca9adafa0c7fa36e691072256bf586eee336391`.

Copyright (C) 2011-2022 Ingo Ruhnke <grumbel@gmail.com>.
The LP2C directory layout and reader in `tools/build_vfs_index.py` follow
The Void Extractor. These derived portions are GPL-3.0-or-later; the complete
license text is supplied in LICENSE. The reader has been adapted for indexing
and port build inputs.

## Python build and test dependencies

Installed separately from requirements.txt; no packages or wheels are vendored.

| Package | Version | Upstream license | Source |
| --- | --- | --- | --- |
| capstone | 5.0.7 | BSD-3-Clause | https://github.com/capstone-engine/capstone |
| unicorn | 2.1.4 | GPL-2.0-only core; BSD Python bindings; component notices apply | https://github.com/unicorn-engine/unicorn |
| pycryptodome | 3.23.0 | BSD and public-domain components; upstream notices apply | https://github.com/Legrandin/pycryptodome |
| pefile | 2024.8.26 | MIT | https://github.com/erocarrera/pefile |

Unicorn is used for regression checks on the build computer; it is not linked
into the Android app. Android SDK/NDK, Java, Visual Studio, Git and XZ Utils
are separately installed tools under their own terms.

## Original games and proprietary middleware

The Void, Tension, their executables, scripts, textures, sound, video and other
resources remain the property of their respective rights holders, including
Ice-Pick Lodge. NVIDIA PhysX and Microsoft DirectX/D3DX inputs retain their
respective owners' terms. None is supplied by this source repository or
relicensed by its GPL grant. Generated C, transformed executable images,
patched game assets and native libraries containing original binary code are
local build outputs and do not become wholly project-owned GPL source.

## Arm ASTC Encoder 5.7.0 — Apache-2.0

Source: https://github.com/ARM-software/astc-encoder

Pinned submodule revision: `baff485b0ff36d2f95d28961605106502c653966`.

Copyright 2011-2026 Arm Limited. The unmodified encoder library is used by the
launcher's ASTC texture converter. Its complete Apache License 2.0 is included
in the APK as `assets/licenses/astcenc.txt` and in the upstream submodule.

## etcpak — BSD-3-Clause

Source: https://github.com/wolfpld/etcpak

Pinned submodule revision: `3d716e1550023dc5ff8b602636af8b76584e0b66`.

The unmodified encoder sources are used by the launcher's ETC2 converter.
The complete copyright notice and license are included in the APK as
`assets/licenses/etcpak.txt` and in the upstream submodule.

## bcdec 0.96 — Unlicense

Source: https://github.com/iOrange/bcdec

Bundled by the pinned etcpak submodule and included by its Decode.cpp.
Distributed under the Unlicense alternative offered by the upstream header:

```text
This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or
distribute this software, either in source code form or as a compiled
binary, for any purpose, commercial or non-commercial, and by any
means.

In jurisdictions that recognize copyright laws, the author or authors
of this software dedicate any and all copyright interest in the
software to the public domain. We make this dedication for the benefit
of the public at large and to the detriment of our heirs and
successors. We intend this dedication to be an overt act of
relinquishment in perpetuity of all present and future rights to this
software under copyright law.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

For more information, please refer to <https://unlicense.org>
```
