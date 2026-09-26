"""PSTBSK-X application frame.
TBSKmodem provides signal detection + payload transport; PSTBSK-X owns framing and CRC.
"""
from __future__ import annotations
import struct, zlib
MAGIC=b"PTX1"
VERSION=1
TYPE_TEXT=1; TYPE_CQ=2; TYPE_REPORT=3; TYPE_QSL=4; TYPE_FINAL=5

_HDR=struct.Struct(">4sBBHH")  # magic, version, type, seq, payload_len

def pack_frame(msg_type:int, seq:int, text:str)->bytes:
    payload=text.encode("utf-8")
    if len(payload)>4096: raise ValueError("payload too large")
    head=_HDR.pack(MAGIC, VERSION, msg_type, seq & 0xffff, len(payload))
    body=head+payload
    crc=zlib.crc32(body) & 0xffffffff
    return body+struct.pack(">I", crc)

def unpack_frame(data:bytes):
    if len(data)<_HDR.size+4: return None
    magic,ver,typ,seq,n=_HDR.unpack_from(data)
    if magic!=MAGIC or ver!=VERSION: return None
    end=_HDR.size+n
    if len(data)<end+4: return None
    body=data[:end]
    got=struct.unpack_from(">I", data, end)[0]
    if (zlib.crc32(body)&0xffffffff)!=got: return None
    try: text=data[_HDR.size:end].decode("utf-8")
    except UnicodeDecodeError: return None
    return {"type":typ,"seq":seq,"text":text,"size":end+4}
