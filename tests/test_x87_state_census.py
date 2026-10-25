"""Census emitted x87 instructions and validate every unique site against PE bytes.

This is static inventory, not evidence that any site ran during gameplay.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import capstone
import pefile

ROOT=Path(__file__).resolve().parents[1]
COMMENT=re.compile(r'/\* 0x([0-9A-F]+): (f\w+|wait)\s*(.*?)\*/')
TRAP=re.compile(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);')
MMX=re.compile(r'/\* 0x([0-9A-F]+): ((?:emms|femms)\b.*?|.*?\bmm[0-7]\b.*?)\*/')


def sha(raw): return hashlib.sha256(raw).hexdigest()


def main():
    game=Path(json.loads((ROOT/'port.json').read_text())['game_directory'])
    decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
    decoder.detail=True
    modules=[]
    for report_path in sorted((ROOT/'generated').glob('*-x86/report.json')):
        report_raw=report_path.read_bytes(); report=json.loads(report_raw)
        directory=report_path.parent; unique={}; mmx={}; sources={}
        for name in report['sources']:
            source=directory/name; raw=source.read_bytes(); sources[str(source.relative_to(ROOT))]=sha(raw)
            text=raw.decode()
            for address,mnemonic,operands in COMMENT.findall(text):
                value={'mnemonic':mnemonic,'operands':operands.strip(),'emission':'body',
                       'source':str(source.relative_to(ROOT))}
                va=int(address,16)
                if va in unique: assert unique[va]['mnemonic']==mnemonic
                else: unique[va]=value
            for address,instruction in MMX.findall(text):
                mnemonic,_,operands=instruction.strip().partition(' ')
                mmx.setdefault(int(address,16),{'mnemonic':mnemonic,'operands':operands.strip(),
                    'emission':'body','source':str(source.relative_to(ROOT))})
            for address,instruction in TRAP.findall(text):
                instruction=json.loads(instruction); mnemonic=instruction.split()[0]
                if not mnemonic.startswith('f')and mnemonic!='wait': continue
                va=int(address,16)
                unique[va]={'mnemonic':mnemonic,'operands':instruction[len(mnemonic):].strip(),
                            'emission':'strict-trap','source':str(source.relative_to(ROOT))}
        if 'input_image'in report:
            image=ROOT/report['input_image']; expected=report.get('rebased_sha256',report['binary_sha256'])
        elif directory.name=='game-x86':
            image=ROOT/'generated/input/Game.exe'; expected=report['binary_sha256']
        elif directory.name=='gamemodule-x86':
            image=game/'bin/win32/GameModule.dll'; expected=report['binary_sha256']
        else: raise ValueError(f'No pinned image for {directory.name}')
        raw=image.read_bytes(); assert sha(raw)==expected
        pe=pefile.PE(data=raw,fast_load=True); base=pe.OPTIONAL_HEADER.ImageBase
        for address,value in list(unique.items())+list(mmx.items()):
            offset=pe.get_offset_from_rva(address-base)
            decoded=next(decoder.disasm(raw[offset:offset+15],address,count=1))
            assert decoded.mnemonic==value['mnemonic'],(directory.name,hex(address),value,decoded.mnemonic)
            value['bytes']=decoded.bytes.hex()
            value['emitted_operands']=value['operands']; value['operands']=decoded.op_str
            form=[]
            for operand in decoded.operands:
                if operand.type==capstone.x86.X86_OP_REG:
                    form.append('reg:'+decoded.reg_name(operand.reg))
                elif operand.type==capstone.x86.X86_OP_MEM:
                    form.append('mem:'+str(operand.size*8))
                elif operand.type==capstone.x86.X86_OP_IMM:
                    form.append('imm:'+str(operand.size*8))
                else:raise ValueError((hex(address),operand.type))
            value['operand_form']=','.join(form)or'none'
            value['prefixes']=[f'{p:02X}'for p in decoded.prefix if p]
        assert all(sha((ROOT/path).read_bytes())==digest for path,digest in sources.items())
        assert report_path.read_bytes()==report_raw and image.read_bytes()==raw
        module={'module':directory.name,'image':str(image),'image_sha256':sha(raw),
                'report_sha256':sha(report_raw),'source_hashes':sources,
                'unique_x87_sites':len(unique),'mnemonics':dict(sorted(Counter(v['mnemonic']for v in unique.values()).items())),
                'operand_forms':dict(sorted(Counter(v['mnemonic']+' '+v['operand_form']for v in unique.values()).items())),
                'sites':{f'{a:08X}':v for a,v in sorted(unique.items())},
                'unique_mmx_alias_sites':len(mmx),
                'mmx_mnemonics':dict(sorted(Counter(v['mnemonic']for v in mmx.values()).items())),
                'mmx_operand_forms':dict(sorted(Counter(v['mnemonic']+' '+v['operand_form']for v in mmx.values()).items())),
                'mmx_sites':{f'{a:08X}':v for a,v in sorted(mmx.items())}}
        modules.append(module)
        print(directory.name,json.dumps(module['mnemonics'],sort_keys=True))
        if mmx:print('  MMX',json.dumps(module['mmx_mnemonics'],sort_keys=True))
    assert len(modules)==9
    output=ROOT/'build/x87-state-audit/census.json'; output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'status':'STATIC_BYTES_VALIDATED','execution_coverage':'UNVERIFIED',
        'original_game_code_executed':False,'modules':modules},indent=2)+'\n')


if __name__=='__main__': main()
