"""Parse 7-series partial bitstreams: FAR writes + FDRI word counts.

Written from the public register/packet tables in Xilinx UG470 (7 Series
FPGAs Configuration User Guide), chapter 5:
  * sync word 0xAA995566
  * Type-1 packet header: [31:29]=001, [28:27]=opcode (00 NOP, 01 read,
    10 write), [26:13]=register address (5 bits used), [10:0]=word count
  * Type-2 packet header: [31:29]=010, [28:27]=opcode, [26:0]=word count
    (payload register = the one addressed by the preceding Type-1)
  * FAR (reg 1) fields: [25:23] block type (000=CLB/interconnect+cfg,
    001=BRAM content), [22] top/bottom, [21:17] row, [16:7] column,
    [6:0] minor
  * FDRI = reg 2.  One frame = 101 32-bit words.

This is how the frame-accounting constants in the bundled device models
were measured (frame counts per column type, the doubled write, the fixed
preamble, and bytes = 404 * frames + 452).
"""
import struct

REG_NAMES = {0: "CRC", 1: "FAR", 2: "FDRI", 3: "FDRO", 4: "CMD", 5: "CTL0",
             6: "MASK", 7: "STAT", 8: "LOUT", 9: "COR0", 10: "MFWR",
             11: "CBC", 12: "IDCODE", 13: "AXSS", 14: "COR1",
             16: "WBSTAR", 17: "TIMER", 22: "BOOTSTS", 24: "CTL1", 31: "BSPI"}

CMD_NAMES = {0: "NULL", 1: "WCFG", 2: "MFW", 3: "DGHIGH/LFRM", 4: "RCFG",
             5: "START", 6: "RCAP", 7: "RCRC", 8: "AGHIGH", 9: "SWITCH",
             10: "GRESTORE", 11: "SHUTDOWN", 12: "GCAPTURE", 13: "DESYNC",
             15: "IPROG", 16: "CRCC", 17: "LTIMER"}

FRAME_WORDS = 101
SYNC = bytes([0xAA, 0x99, 0x55, 0x66])


def far_fields(v):
    """Decode a FAR register value -> (blk, top, row, col, minor)."""
    blk = (v >> 23) & 0x7
    top = (v >> 22) & 0x1
    row = (v >> 17) & 0x1F
    col = (v >> 7) & 0x3FF
    minor = v & 0x7F
    return blk, top, row, col, minor


def parse(path):
    """Parse one partial bitstream file.

    Returns a dict: file_bytes, presync_bytes, fdri_words, fdri_frames,
    cmds (decoded CMD writes in order), far_writes, and fdri_events as a
    list of (far_value, word_count) with the FAR in effect at each FDRI
    write.  Returns None if no sync word is found.
    """
    with open(path, "rb") as f:
        data = f.read()
    i = data.find(SYNC)
    if i < 0:
        return None
    p = i + 4
    n = len(data)
    cur_reg = None
    fdri_words = 0
    far_writes = []
    fdri_events = []
    last_far = None
    cmds = []
    while p + 4 <= n:
        (word,) = struct.unpack(">I", data[p:p + 4])
        p += 4
        typ = word >> 29
        if typ == 1:
            op = (word >> 27) & 0x3
            reg = (word >> 13) & 0x1F
            wc = word & 0x7FF
            if op == 2:  # write
                cur_reg = reg
                payload = struct.unpack(">%dI" % wc, data[p:p + 4 * wc]) if wc else ()
                p += 4 * wc
                if reg == 1 and wc:
                    for v in payload:
                        far_writes.append(v)
                        last_far = v
                elif reg == 4 and wc:
                    for v in payload:
                        cmds.append(CMD_NAMES.get(v, hex(v)))
                elif reg == 2 and wc:
                    fdri_words += wc
                    fdri_events.append((last_far, wc))
            else:
                p += 4 * (word & 0x7FF)
        elif typ == 2:
            op = (word >> 27) & 0x3
            wc = word & 0x7FFFFFF
            if op == 2 and cur_reg == 2:
                fdri_words += wc
                fdri_events.append((last_far, wc))
            p += 4 * wc
    return {
        "path": path,
        "file_bytes": len(data),
        "presync_bytes": i,
        "fdri_words": fdri_words,
        "fdri_frames": fdri_words / FRAME_WORDS,
        "cmds": cmds,
        "far_writes": far_writes,
        "fdri_events": fdri_events,
    }


def report(res):
    """Human-readable report of a parse() result."""
    if res is None:
        return "no sync word found"
    lines = []
    lines.append(res["path"])
    lines.append("  file bytes=%d header(pre-sync)=%d" %
                 (res["file_bytes"], res["presync_bytes"]))
    lines.append("  FDRI total words=%d -> frames=%.2f" %
                 (res["fdri_words"], res["fdri_frames"]))
    lines.append("  FAR writes=%d  CMD sequence: %s" %
                 (len(res["far_writes"]), " ".join(res["cmds"][:40])))
    for far, wc in res["fdri_events"]:
        if far is None:
            lines.append("  FDRI write: FAR=<none> words=%d frames=%.2f"
                         % (wc, wc / FRAME_WORDS))
            continue
        blk, top, row, col, minor = far_fields(far)
        lines.append("  FDRI write: FAR=0x%08X blk=%d top=%d row=%d col=%d "
                     "minor=%d words=%d frames=%.2f"
                     % (far, blk, top, row, col, minor, wc, wc / FRAME_WORDS))
    return "\n".join(lines)
