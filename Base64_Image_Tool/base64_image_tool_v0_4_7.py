# ============================================

# Script Name:   Base64 Image Tool
# Description:   Base64 encoding converts binary image data into ASCII text using a specific alphabet of 64 characters. 
#                This transformation allows images to be represented as text strings that can be embedded directly into scripts as C4D dialog graphics.
#                Main focus of this tool is for optimiazation of Picture to Base64 code, but it has also a small editor with some capabilities.
# Author:        RiesiSir | mail@andreasriesener.com
# Version:       0.4.7
# Date:          2026-05-02
# C4D Version:   2026.2
# ============================================

"""
Base64 Image Tool v0.4.7 for Cinema 4D
Script Manager: Extensions -> Script Manager -> Execute
"""

import c4d
import base64
import os
import subprocess
import sys
import webbrowser

# ---------------------------------------------------------------------------
# Main Dialog IDs
# ---------------------------------------------------------------------------
BTN_LOAD          = 1001
BTN_ENCODE        = 1002
BTN_COPY          = 1003
BTN_CLEAR         = 1004
BTN_NEW_CANVAS    = 1006
BTN_APPLY         = 1008  # Apply Resize/Hard Alias destructively to canvas
BTN_SAVE_PNG      = 1009
BTN_CLIP_LOAD     = 1026
TXT_STATUS        = 1011
TXT_RESULT        = 1012
CHK_AA            = 1013
CHK_RESIZE        = 1014
CHK_PROPORTIONAL  = 1015
EDT_WIDTH         = 1016
EDT_HEIGHT        = 1017
TXT_ORIG_SIZE     = 1018
CHK_CHUNKS        = 1019
EDT_THRESHOLD     = 1025
EDT_DECODE_INPUT  = 1020
BTN_DECODE        = 1021
EDT_NEW_W         = 1022
EDT_NEW_H         = 1023
BTN_NEW_CONFIRM   = 1024

GRP_MAIN          = 10000
GRP_FILE          = 10001
GRP_BTNS          = 10004
GRP_OPTIONS       = 10005
GRP_RES           = 10006
GRP_EDITOR_BTNS   = 10008
GRP_TABS          = 10009
GRP_ENCODE_PAGE   = 10010
GRP_DECODE_PAGE   = 10011
PRV_STRIP_UA      = 10020
SIG_AREA          = 10099

# ---------------------------------------------------------------------------
# Preview / Editor Dialog IDs
# ---------------------------------------------------------------------------
PRV_USER_AREA     = 2001
PRV_VIEW_GRP      = 20010
PRV_GRP_MAIN      = 20000
PRV_GRP_TOOLBAR   = 20001

BTN_TOOL_FILL     = 3003
BTN_TOOL_CLEAR    = 3004
BTN_AUTO_CROP     = 3005
BTN_TOOL_PENCIL   = 3006
BTN_TOOL_LINE     = 3007
BTN_TOOL_RECT     = 3008
BTN_TOOL_CIRCLE   = 3009
BTN_MODE_VIEW     = 3010
CLR_FOREGROUND    = 3020
CHK_FILLED_SHAPE  = 3021
PRV_CHK_AA        = 3030
PRV_EDT_THRESHOLD = 3031
PRV_CHK_RESIZE    = 3032
PRV_EDT_W         = 3033
PRV_EDT_H         = 3034
PRV_CHK_PROP      = 3035
PRV_BTN_APPLY     = 3036
PRV_GRP_FILTERS   = 3040

DISPLAY_LINE_WIDTH = 76

CHECKER_A = (60, 60, 60)
CHECKER_B = (40, 40, 40)

MAX_UNDO  = 50


class UndoStack(object):

    def __init__(self, max_steps=MAX_UNDO):
        self._max  = max_steps
        self._undo = []
        self._redo = []

    def push(self, canvas):
        self._undo.append(canvas.clone())
        if len(self._undo) > self._max:
            self._undo.pop(0)
        self._redo = []

    def undo(self, current_canvas):
        if not self._undo:
            return None
        self._redo.append(current_canvas.clone())
        return self._undo.pop()

    def redo(self, current_canvas):
        if not self._redo:
            return None
        self._undo.append(current_canvas.clone())
        return self._redo.pop()

    def clear(self):
        self._undo = []
        self._redo = []

    def can_undo(self):
        return len(self._undo) > 0

    def can_redo(self):
        return len(self._redo) > 0

    def undo_count(self):
        return len(self._undo)

    def redo_count(self):
        return len(self._redo)


# ---------------------------------------------------------------------------
# Canvas State
# ---------------------------------------------------------------------------
class CanvasState(object):

    def __init__(self, w, h, fill=(0, 0, 0, 0)):
        self.w   = w
        self.h   = h
        self._px = [fill] * (w * h)

    def get(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self._px[y * self.w + x]
        return (0, 0, 0, 0)

    def set(self, x, y, rgba):
        if 0 <= x < self.w and 0 <= y < self.h:
            self._px[y * self.w + x] = rgba

    def clear(self):
        self._px = [(0, 0, 0, 0)] * (self.w * self.h)

    def clone(self):
        c = CanvasState(self.w, self.h)
        c._px = list(self._px)
        return c

    def auto_crop(self):
        """
        Returns a new CanvasState trimmed to the bounding box of non-transparent pixels.
        If the canvas is entirely transparent, returns a 1x1 transparent canvas.
        """
        min_x, min_y = self.w, self.h
        max_x, max_y = -1, -1
        for cy in range(self.h):
            for cx in range(self.w):
                if self._px[cy * self.w + cx][3] > 0:
                    if cx < min_x: min_x = cx
                    if cx > max_x: max_x = cx
                    if cy < min_y: min_y = cy
                    if cy > max_y: max_y = cy
        if max_x < 0:
            return CanvasState(1, 1, fill=(0, 0, 0, 0))
        new_w = max_x - min_x + 1
        new_h = max_y - min_y + 1
        cropped = CanvasState(new_w, new_h)
        for cy in range(new_h):
            for cx in range(new_w):
                cropped._px[cy * new_w + cx] = self._px[(cy + min_y) * self.w + (cx + min_x)]
        return cropped

    def flood_fill(self, x, y, new_rgba):
        target = self.get(x, y)
        if target == new_rgba:
            return
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if not (0 <= cx < self.w and 0 <= cy < self.h):
                continue
            if self.get(cx, cy) != target:
                continue
            self.set(cx, cy, new_rgba)
            stack.extend([(cx+1,cy),(cx-1,cy),(cx,cy+1),(cx,cy-1)])

    def to_bitmap(self):
        bmp = c4d.bitmaps.BaseBitmap()
        bmp.Init(self.w, self.h, 32)
        alpha_ch = bmp.AddChannel(True, True)
        for y in range(self.h):
            for x in range(self.w):
                r, g, b, a = self._px[y * self.w + x]
                bmp.SetPixel(x, y, r, g, b)
                bmp.SetAlphaPixel(alpha_ch, x, y, a)
        return bmp

    @classmethod
    def from_bitmap(cls, bmp):
        """
        Build CanvasState from a BaseBitmap.
        C4D does not always expose alpha via GetInternalChannel() after InitWith() -
        we try GetInternalChannel() first, then fall back to GetAlphaPixel on
        channel index 0 directly, and finally check all channels via GetChannelCount.
        """
        w, h     = bmp.GetBw(), bmp.GetBh()
        alpha_ch = bmp.GetInternalChannel()

        # Fallback: iterate channels if GetInternalChannel returns None
        if alpha_ch is None:
            count = bmp.GetChannelCount()
            for i in range(count):
                ch = bmp.GetChannelNum(i)
                if ch is not None:
                    alpha_ch = ch
                    break

        cs = cls(w, h)
        for y in range(h):
            for x in range(w):
                r, g, b = bmp.GetPixel(x, y)
                a = bmp.GetAlphaPixel(alpha_ch, x, y) if alpha_ch else 255
                cs._px[y * w + x] = (r, g, b, a)
        return cs

    @classmethod
    def from_data_url(cls, data_url):
        """
        Accept full Data URL or raw Base64 string.
        Uses pure Python PNG reader to guarantee correct RGBA - no C4D bitmap pipeline.
        """
        cleaned = "".join(c for c in data_url if c in
                          "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                          "0123456789+/=:;,.-_")
        if "base64," in cleaned:
            b64_data = cleaned.split("base64,", 1)[1]
        else:
            b64_data = cleaned

        missing = len(b64_data) % 4
        if missing:
            b64_data += "=" * (4 - missing)

        try:
            raw = base64.b64decode(b64_data)
        except Exception as e:
            raise ValueError("Base64 decode failed: {}".format(e))

        try:
            pixels, w, h = _read_png_rgba(raw)
        except Exception as e:
            raise ValueError("PNG decode failed: {}".format(e))

        cs = cls(w, h)
        cs._px = list(pixels)
        return cs


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def copy_to_clipboard(text):
    try:
        if sys.platform == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            return True
        elif sys.platform == "win32":
            tmp = get_temp_path("c4d_clip_tmp.txt")
            with open(tmp, "w", encoding="utf-8") as f_tmp:
                f_tmp.write(text)
            with open(tmp, "rb") as f_in:
                subprocess.run(["cmd", "/c", "clip"], stdin=f_in)
            try:
                os.remove(tmp)
            except Exception:
                pass
            return True
        else:
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    p.communicate(text.encode("utf-8"))
                    return True
                except FileNotFoundError:
                    continue
    except Exception as e:
        print("Clipboard error:", e)
    return False


def load_image_from_clipboard():
    """
    Read an image from the system clipboard.
    Returns a temp file path (PNG) on success, or raises an exception.
    Platform:
      Windows -- PowerShell System.Windows.Forms.Clipboard -> PNG bytes
      macOS   -- osascript writes clipboard TIFF -> temp file, C4D loads it
      Linux   -- xclip -t image/png -o
    """
    tmp = get_temp_path("c4d_b64_clip_tmp.png")

    if sys.platform == "win32":
        # PowerShell: get clipboard image and save as PNG
        tmp_fwd = tmp.replace("\\", "/")
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$img = [System.Windows.Forms.Clipboard]::GetImage(); "
            "if ($img -eq $null) { exit 1 }; "
            "$img.Save('" + tmp_fwd + "', "
            "[System.Drawing.Imaging.ImageFormat]::Png); exit 0"
        )
        # Hide the PowerShell window via STARTUPINFO
        si = subprocess.STARTUPINFO()
        si.dwFlags    |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-WindowStyle", "Hidden",
             "-Command", ps_script],
            capture_output=True,
            startupinfo=si
        )
        if result.returncode != 0:
            raise ValueError("No image in clipboard (Windows).")
        return tmp

    elif sys.platform == "darwin":
        # osascript: write clipboard TIFF to temp, then convert to PNG via sips
        tiff_tmp = get_temp_path("c4d_b64_clip_tmp.tiff")
        osa_lines = [
            "set theFile to POSIX file \"" + tiff_tmp + "\"",
            "set theData to the clipboard as TIFF picture",
            "set fileRef to open for access theFile with write permission",
            "write theData to fileRef",
            "close access fileRef",
        ]
        result = subprocess.run(
            ["osascript"] + [item for line in osa_lines for item in ["-e", line]],
            capture_output=True
        )
        if result.returncode != 0:
            raise ValueError("No image in clipboard (macOS).")
        result2 = subprocess.run(
            ["sips", "-s", "format", "png", tiff_tmp, "--out", tmp],
            capture_output=True
        )
        try:
            os.remove(tiff_tmp)
        except Exception:
            pass
        if result2.returncode != 0:
            raise ValueError("Could not convert clipboard image to PNG.")
        return tmp

    else:
        # Linux: xclip
        for cmd in [["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                    ["xsel", "--clipboard", "--output"]]:
            try:
                result = subprocess.run(cmd, capture_output=True)
                if result.returncode == 0 and result.stdout:
                    with open(tmp, "wb") as f:
                        f.write(result.stdout)
                    return tmp
            except FileNotFoundError:
                continue
        raise ValueError("No image in clipboard (Linux). Install xclip.")


def get_mime(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".gif": "image/gif",
        ".bmp": "image/bmp",  ".webp": "image/webp",
        ".svg": "image/svg+xml", ".tif": "image/tiff",
        ".tiff": "image/tiff",  ".hdr": "image/vnd.radiance",
        ".exr": "image/x-exr", ".ico": "image/x-icon",
    }.get(ext, "application/octet-stream")


def format_base64_python(b64_string, width=DISPLAY_LINE_WIDTH):
    # Format as Python string chunks for direct code use:
    # (
    #     "chunk1"
    #     "chunk2"
    # )
    chunks = [b64_string[i:i+width] for i in range(0, len(b64_string), width)]
    lines  = ['    "{}"'.format(c) for c in chunks]
    inner  = "\n".join(lines)
    return "(\n{}\n)".format(inner)


def get_temp_path(filename):
    try:
        folder = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_TEMP)
    except Exception:
        folder = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
    return os.path.join(folder, filename)


def get_image_size(filepath):
    bmp = c4d.bitmaps.BaseBitmap()
    result, _ = bmp.InitWith(filepath)
    if result == c4d.IMAGERESULT_OK:
        return bmp.GetBw(), bmp.GetBh()
    return 0, 0


def hard_alias_alpha(src_bmp, alpha_threshold=32):
    # For images WITH alpha: threshold alpha channel.
    # For images WITHOUT alpha (white/black): threshold RGB luminance.
    # Luminance threshold: dark pixels (<128 lum) become black, rest white.
    w, h      = src_bmp.GetBw(), src_bmp.GetBh()
    alpha_ch  = src_bmp.GetInternalChannel()
    has_alpha = alpha_ch is not None
    out       = c4d.bitmaps.BaseBitmap()
    out.Init(w, h, 32)
    out_alpha = out.AddChannel(True, True)
    for y in range(h):
        for x in range(w):
            r, g, b = src_bmp.GetPixel(x, y)
            if has_alpha:
                a     = src_bmp.GetAlphaPixel(alpha_ch, x, y)
                new_a = 255 if a >= alpha_threshold else 0
                if new_a == 0:
                    r, g, b = 255, 255, 255
            else:
                # No alpha - threshold by luminance
                # Low luminance = dark pixel = opaque; high = bright = transparent
                lum   = int(0.299 * r + 0.587 * g + 0.114 * b)
                new_a = 255 if lum < (255 - alpha_threshold) else 0
                r, g, b = (0, 0, 0) if new_a == 255 else (255, 255, 255)
            out.SetPixel(x, y, r, g, b)
            out.SetAlphaPixel(out_alpha, x, y, new_a)
    return out


def resize_bitmap(src_bmp, target_w, target_h):
    src_w, src_h = src_bmp.GetBw(), src_bmp.GetBh()
    alpha_ch     = src_bmp.GetInternalChannel()
    has_alpha    = alpha_ch is not None
    if not has_alpha:
        out = c4d.bitmaps.BaseBitmap()
        out.Init(target_w, target_h, 24)
        src_bmp.ScaleIt(out, 256, True, True)
        return out
    white_rgb = c4d.bitmaps.BaseBitmap()
    white_rgb.Init(src_w, src_h, 24)
    for y in range(src_h):
        for x in range(src_w):
            r, g, b = src_bmp.GetPixel(x, y)
            a = src_bmp.GetAlphaPixel(alpha_ch, x, y)
            t = a / 255.0
            white_rgb.SetPixel(x, y,
                int(t*r+(1.0-t)*255), int(t*g+(1.0-t)*255), int(t*b+(1.0-t)*255))
    scaled_rgb = c4d.bitmaps.BaseBitmap()
    scaled_rgb.Init(target_w, target_h, 24)
    white_rgb.ScaleIt(scaled_rgb, 256, True, True)
    alpha_gray = c4d.bitmaps.BaseBitmap()
    alpha_gray.Init(src_w, src_h, 24)
    for y in range(src_h):
        for x in range(src_w):
            a = src_bmp.GetAlphaPixel(alpha_ch, x, y)
            alpha_gray.SetPixel(x, y, a, a, a)
    scaled_alpha = c4d.bitmaps.BaseBitmap()
    scaled_alpha.Init(target_w, target_h, 24)
    alpha_gray.ScaleIt(scaled_alpha, 256, True, True)
    out = c4d.bitmaps.BaseBitmap()
    out.Init(target_w, target_h, 32)
    out_alpha = out.AddChannel(True, True)
    for y in range(target_h):
        for x in range(target_w):
            r, g, b  = scaled_rgb.GetPixel(x, y)
            ag, _, _ = scaled_alpha.GetPixel(x, y)
            out.SetPixel(x, y, r, g, b)
            out.SetAlphaPixel(out_alpha, x, y, ag)
    return out


def process_bitmap(filepath, use_resize, target_w, target_h, use_hard_alias, threshold=32):
    src = c4d.bitmaps.BaseBitmap()
    src.InitWith(filepath)
    bmp = src
    if use_resize:
        bmp = resize_bitmap(bmp, target_w, target_h)
    if use_hard_alias:
        bmp = hard_alias_alpha(bmp, alpha_threshold=threshold)
    return bmp


def make_flat_preview(src_bmp, bg_r, bg_g, bg_b):
    w, h      = src_bmp.GetBw(), src_bmp.GetBh()
    alpha_ch  = src_bmp.GetInternalChannel()
    has_alpha = alpha_ch is not None
    out = c4d.bitmaps.BaseBitmap()
    out.Init(w, h, 24)
    for y in range(h):
        for x in range(w):
            r, g, b = src_bmp.GetPixel(x, y)
            if has_alpha:
                a = src_bmp.GetAlphaPixel(alpha_ch, x, y)
                t = a / 255.0
                r = int(t*r+(1.0-t)*bg_r)
                g = int(t*g+(1.0-t)*bg_g)
                b = int(t*b+(1.0-t)*bg_b)
            out.SetPixel(x, y, r, g, b)
    return out


def _read_png_rgba(data):
    """
    Pure Python PNG reader. Returns (pixels, w, h) where pixels is a list of (r,g,b,a).
    Supports 8-bit RGBA (color type 6) and 8-bit RGB (color type 2).
    Compatible with both Python 2 and Python 3 byte indexing.
    """
    import struct, zlib

    def byte_at(d, i):
        v = d[i]
        return v if isinstance(v, int) else ord(v)

    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG file")

    pos       = 8
    chunks    = {}
    idat_list = []

    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        ctype  = data[pos+4:pos+8]
        cdata  = data[pos+8:pos+8+length]
        pos   += 12 + length
        if ctype == b"IHDR":
            chunks["IHDR"] = cdata
        elif ctype == b"IDAT":
            idat_list.append(cdata)
        elif ctype == b"IEND":
            break

    ihdr       = chunks["IHDR"]
    w, h       = struct.unpack(">II", ihdr[:8])
    bit_depth  = byte_at(ihdr, 8)
    color_type = byte_at(ihdr, 9)

    if bit_depth != 8:
        raise ValueError("Only 8-bit PNG supported, got {}".format(bit_depth))

    raw    = zlib.decompress(b"".join(idat_list))
    pixels = []

    if color_type == 6:  # RGBA
        stride = 1 + w * 4
        for y in range(h):
            base = y * stride + 1
            for x in range(w):
                o = base + x * 4
                pixels.append((byte_at(raw, o), byte_at(raw, o+1),
                                byte_at(raw, o+2), byte_at(raw, o+3)))
    elif color_type == 2:  # RGB
        stride = 1 + w * 3
        for y in range(h):
            base = y * stride + 1
            for x in range(w):
                o = base + x * 3
                pixels.append((byte_at(raw, o), byte_at(raw, o+1),
                                byte_at(raw, o+2), 255))
    else:
        raise ValueError("Unsupported PNG color type: {}".format(color_type))

    return pixels, w, h


def _write_png_rgba(canvas):
    """
    Pure Python PNG encoder for RGBA CanvasState.
    Writes color type 6 (RGBA 8-bit) - alpha is always preserved.
    """
    import struct, zlib

    w, h = canvas.w, canvas.h

    def make_chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig       = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    ihdr      = make_chunk(b"IHDR", ihdr_data)

    raw_rows = []
    for y in range(h):
        row = b"\x00"
        for x in range(w):
            r, g, b, a = canvas.get(x, y)
            row += struct.pack("BBBB", r, g, b, a)
        raw_rows.append(row)

    idat = make_chunk(b"IDAT", zlib.compress(b"".join(raw_rows), 9))
    iend = make_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def canvas_to_data_url(canvas):
    """Encode canvas directly to PNG bytes using pure Python writer - no bitmap roundtrip."""
    raw = _write_png_rgba(canvas)
    b64 = base64.b64encode(raw).decode("ascii")
    return "data:image/png;base64,{}".format(b64), b64, raw


# ---------------------------------------------------------------------------
# Editor UserArea
# ---------------------------------------------------------------------------
class EditorUserArea(c4d.gui.GeUserArea):

    TOOL_PENCIL = 0
    TOOL_FILL   = 2
    TOOL_LINE   = 3
    TOOL_RECT   = 4
    TOOL_CIRCLE = 5

    def __init__(self):
        self._canvas       = None
        self._draw_mode    = False
        self._tool         = self.TOOL_PENCIL
        self._fg_color     = (255, 255, 255, 255)
        self._filled_shape = False
        self._drawn_w      = 0
        self._drawn_h      = 0
        self._cell_x       = 0
        self._cell_y       = 0
        self._cell_size    = 1
        self._on_change    = None
        self._undo_stack   = UndoStack()
        # Ghost preview for shape tools (set during drag, cleared on mouse-up)
        self._ghost_pixels = []   # list of (cx, cy, rgba)

    def SetCanvas(self, canvas):
        self._canvas  = canvas
        self._drawn_w = 0
        self._drawn_h = 0
        self._undo_stack.clear()
        self.Redraw()


    def PushUndo(self):
        if self._canvas:
            self._undo_stack.push(self._canvas)

    def Undo(self):
        if not self._canvas or not self._undo_stack.can_undo():
            return False
        prev = self._undo_stack.undo(self._canvas)
        if prev:
            self._canvas = prev
            self.Redraw()
            if self._on_change:
                self._on_change()
            return True
        return False

    def Redo(self):
        if not self._canvas or not self._undo_stack.can_redo():
            return False
        nxt = self._undo_stack.redo(self._canvas)
        if nxt:
            self._canvas = nxt
            self.Redraw()
            if self._on_change:
                self._on_change()
            return True
        return False

    def GetUndoCount(self):
        return self._undo_stack.undo_count()

    def GetRedoCount(self):
        return self._undo_stack.redo_count()

    def SetDrawMode(self, enabled):
        self._draw_mode = enabled
        self.Redraw()

    def SetTool(self, tool):
        self._tool = tool

    def SetForegroundColor(self, r, g, b, a=255):
        self._fg_color = (r, g, b, a)

    def SetFilledShape(self, filled):
        self._filled_shape = filled

    def SetChangeCallback(self, fn):
        self._on_change = fn

    # ------------------------------------------------------------------
    # Bresenham / shape helpers  (return list of (cx,cy) pixel coords)
    # ------------------------------------------------------------------
    @staticmethod
    def _line_pixels(x0, y0, x1, y1):
        """Bresenham line."""
        pts = []
        dx, dy   = abs(x1 - x0), abs(y1 - y0)
        sx, sy   = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err      = dx - dy
        while True:
            pts.append((x0, y0))
            if x0 == x1 and y0 == y1:
                break
            e2 = err * 2
            if e2 > -dy:
                err -= dy
                x0  += sx
            if e2 < dx:
                err += dx
                y0  += sy
        return pts

    @staticmethod
    def _rect_pixels(x0, y0, x1, y1, filled):
        """Axis-aligned rectangle, filled or outline."""
        lx, rx = min(x0, x1), max(x0, x1)
        ty, by = min(y0, y1), max(y0, y1)
        pts = []
        if filled:
            for cy in range(ty, by + 1):
                for cx in range(lx, rx + 1):
                    pts.append((cx, cy))
        else:
            for cx in range(lx, rx + 1):
                pts.append((cx, ty))
                pts.append((cx, by))
            for cy in range(ty + 1, by):
                pts.append((lx, cy))
                pts.append((rx, cy))
        return pts

    @staticmethod
    def _ellipse_pixels(x0, y0, x1, y1, filled):
        """
        Robust ellipse/circle rasterizer using direct algebraic intersection.
        For each row y in the bounding box, compute the x-span where the pixel
        center lies inside (or on) the ellipse.  This guarantees no gaps.
        Outline = pixels whose center is inside the ellipse but whose at least
        one 4-neighbour is outside -> avoids the double-ring issue.
        """
        import math
        lx, rx = min(x0, x1), max(x0, x1)
        ty, by = min(y0, y1), max(y0, y1)

        # ellipse centre and semi-axes (pixel centres, so +0.5 offset)
        cx  = (lx + rx) / 2.0
        cy  = (ty + by) / 2.0
        a   = (rx - lx + 1) / 2.0   # semi-axis x
        b   = (by - ty + 1) / 2.0   # semi-axis y

        if a < 0.5 or b < 0.5:
            pts = []
            for py in range(ty, by + 1):
                for px in range(lx, rx + 1):
                    pts.append((px, py))
            return pts

        def inside(px, py):
            dx = (px + 0.5 - cx) / a
            dy = (py + 0.5 - cy) / b
            return dx * dx + dy * dy <= 1.0

        pts = []
        if filled:
            for py in range(ty, by + 1):
                # x-span: solve ((px+0.5-cx)/a)^2 + ((py+0.5-cy)/b)^2 = 1
                fy = (py + 0.5 - cy) / b
                if abs(fy) > 1.0:
                    continue
                half_x = a * math.sqrt(max(0.0, 1.0 - fy * fy))
                x_left  = int(math.ceil(cx - half_x - 0.5))
                x_right = int(math.floor(cx + half_x - 0.5))
                for px in range(max(lx, x_left), min(rx, x_right) + 1):
                    pts.append((px, py))
        else:
            # Outline: pixels inside the ellipse that have at least one
            # 4-neighbour outside
            for py in range(ty, by + 1):
                fy = (py + 0.5 - cy) / b
                if abs(fy) > 1.0:
                    continue
                half_x = a * math.sqrt(max(0.0, 1.0 - fy * fy))
                x_left  = int(math.ceil(cx - half_x - 0.5))
                x_right = int(math.floor(cx + half_x - 0.5))
                for px in range(max(lx, x_left), min(rx, x_right) + 1):
                    if (not inside(px - 1, py) or not inside(px + 1, py) or
                            not inside(px, py - 1) or not inside(px, py + 1)):
                        pts.append((px, py))
        return pts

    def GetDrawnSize(self):
        return self._drawn_w, self._drawn_h

    def GetMinSize(self):
        return 1, 1

    def _area_to_canvas(self, ax, ay):
        if self._cell_size < 1:
            return -1, -1
        return (ax - self._cell_x) // self._cell_size, (ay - self._cell_y) // self._cell_size

    def InputEvent(self, msg):
        device  = msg.GetInt32(c4d.BFM_INPUT_DEVICE)
        channel = msg.GetInt32(c4d.BFM_INPUT_CHANNEL)

        # Keyboard: always handle regardless of draw mode
        if device == c4d.BFM_INPUT_KEYBOARD:
            qual = msg.GetInt32(c4d.BFM_INPUT_QUALIFIER)
            ctrl = bool(qual & c4d.QUALIFIER_CTRL)
            shft = bool(qual & c4d.QUALIFIER_SHIFT)
            if ctrl and not shft and channel == ord("Z"):
                if self.Undo() and self._on_change:
                    self._on_change()
                return True
            if ctrl and (channel == ord("Y") or (shft and channel == ord("Z"))):
                if self.Redo() and self._on_change:
                    self._on_change()
                return True
            return True

        if not self._draw_mode or not self._canvas:
            return True

        if device != c4d.BFM_INPUT_MOUSE:
            return True

        is_left  = (channel == c4d.BFM_INPUT_MOUSELEFT)
        is_right = (channel == c4d.BFM_INPUT_MOUSERIGHT)
        if not (is_left or is_right):
            return True

        # BFM_INPUT_X/Y are global window coords - subtract Local2Global offset
        gx = msg.GetInt32(c4d.BFM_INPUT_X)
        gy = msg.GetInt32(c4d.BFM_INPUT_Y)
        local = self.Local2Global()
        ax = gx - local["x"]
        ay = gy - local["y"]

        draw_color  = (0, 0, 0, 0) if is_right else self._fg_color
        shape_tools = (self.TOOL_LINE, self.TOOL_RECT, self.TOOL_CIRCLE)

        if self._tool in shape_tools:
            # Shape tools: ghost preview during drag, commit on mouse-up
            self.PushUndo()
            cx0, cy0 = self._area_to_canvas(ax, ay)

            self.MouseDragStart(
                channel, float(ax), float(ay),
                c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE | c4d.MOUSEDRAGFLAGS_NOMOVE
            )

            mx, my = float(ax), float(ay)

            while True:
                result, dx, dy, channels = self.MouseDrag()
                if result != c4d.MOUSEDRAGRESULT_CONTINUE:
                    break
                mx -= dx
                my -= dy
                cx1, cy1 = self._area_to_canvas(int(mx), int(my))
                # Rebuild ghost pixels for current drag endpoint
                if self._tool == self.TOOL_LINE:
                    pts = self._line_pixels(cx0, cy0, cx1, cy1)
                elif self._tool == self.TOOL_RECT:
                    pts = self._rect_pixels(cx0, cy0, cx1, cy1, self._filled_shape)
                else:
                    pts = self._ellipse_pixels(cx0, cy0, cx1, cy1, self._filled_shape)
                self._ghost_pixels = [(px, py, draw_color) for (px, py) in pts]
                self.Redraw()

            self.MouseDragEnd()

            # Commit ghost pixels to canvas
            if self._ghost_pixels:
                for px, py, col in self._ghost_pixels:
                    self._canvas.set(px, py, col)
            self._ghost_pixels = []
            self.Redraw()
            if self._on_change:
                self._on_change()

        elif self._tool == self.TOOL_FILL:
            # Fill / Fill-Erase: single click, no drag loop needed
            self.PushUndo()
            cx, cy = self._area_to_canvas(ax, ay)
            self._canvas.flood_fill(cx, cy, draw_color)
            self.Redraw()
            if self._on_change:
                self._on_change()

        else:
            # Pencil / Erase: paint on drag
            self.PushUndo()
            self.MouseDragStart(
                channel, float(ax), float(ay),
                c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE | c4d.MOUSEDRAGFLAGS_NOMOVE
            )
            mx, my = float(ax), float(ay)
            cx, cy = self._area_to_canvas(int(mx), int(my))
            self._canvas.set(cx, cy, draw_color)
            self.Redraw()

            while True:
                result, dx, dy, channels = self.MouseDrag()
                if result != c4d.MOUSEDRAGRESULT_CONTINUE:
                    break
                if dx == 0.0 and dy == 0.0:
                    continue
                mx -= dx
                my -= dy
                cx, cy = self._area_to_canvas(int(mx), int(my))
                self._canvas.set(cx, cy, draw_color)
                self.Redraw()

            self.MouseDragEnd()
            if self._on_change:
                self._on_change()

        return True

    def DrawMsg(self, x1, y1, x2, y2, msg):
        self.OffScreenOn()
        self.SetClippingRegion(x1, y1, x2, y2)

        col              = self.GetColorRGB(c4d.COLOR_BG)
        bg_r, bg_g, bg_b = col["r"], col["g"], col["b"]
        bg_vec           = c4d.Vector(bg_r/255.0, bg_g/255.0, bg_b/255.0)
        self.DrawSetPen(bg_vec)
        self.DrawRectangle(x1, y1, x2, y2)

        # View mode with flat bitmap (ViewDialog or file pipeline preview)
        if not self._canvas:
            flat = getattr(self, "_flat_bmp", None)
            if flat:
                ow = flat.GetBw()
                oh = flat.GetBh()
                aw = x2 - x1
                ah = y2 - y1
                scale  = min(float(aw) / ow, float(ah) / oh)
                dw     = max(1, int(ow * scale))
                dh     = max(1, int(oh * scale))
                ox     = x1 + (aw - dw) // 2
                oy     = y1 + (ah - dh) // 2
                scaled = c4d.bitmaps.BaseBitmap()
                scaled.Init(dw, dh, 24)
                flat.ScaleIt(scaled, 256, True, True)
                self.DrawBitmap(scaled, ox, oy, dw, dh, 0, 0, dw, dh, c4d.BMP_NORMAL)
                self._drawn_w = dw
                self._drawn_h = dh
            else:
                self.DrawSetTextCol(c4d.Vector(0.5, 0.5, 0.5), bg_vec)
                self.DrawText("No canvas  |  Use New Canvas or Load into Editor", x1+8, y1+8)
            return

        cw        = self._canvas.w
        ch        = self._canvas.h
        area_w    = x2 - x1
        area_h    = y2 - y1
        cell_size = max(1, min(area_w // cw, area_h // ch))
        draw_w    = cw * cell_size
        draw_h    = ch * cell_size
        off_x     = x1 + (area_w - draw_w) // 2
        off_y     = y1 + (area_h - draw_h) // 2

        self._cell_x    = off_x
        self._cell_y    = off_y
        self._cell_size = cell_size

        if self._draw_mode:
            # Draw mode: checkerboard + pixels + optional grid
            for cy in range(ch):
                for cx in range(cw):
                    checker     = ((cx + cy) % 2 == 0)
                    cr, cg, cb  = CHECKER_A if checker else CHECKER_B
                    px = off_x + cx * cell_size
                    py = off_y + cy * cell_size
                    self.DrawSetPen(c4d.Vector(cr/255.0, cg/255.0, cb/255.0))
                    self.DrawRectangle(px, py, px+cell_size-1, py+cell_size-1)

            for cy in range(ch):
                for cx in range(cw):
                    r, g, b, a = self._canvas.get(cx, cy)
                    if a == 0:
                        continue
                    t           = a / 255.0
                    checker     = ((cx + cy) % 2 == 0)
                    br, bg_, bb = CHECKER_A if checker else CHECKER_B
                    px = off_x + cx * cell_size
                    py = off_y + cy * cell_size
                    self.DrawSetPen(c4d.Vector(
                        (t*r+(1-t)*br)/255.0,
                        (t*g+(1-t)*bg_)/255.0,
                        (t*b+(1-t)*bb)/255.0))
                    self.DrawRectangle(px, py, px+cell_size-1, py+cell_size-1)

            if cell_size >= 5:
                self.DrawSetPen(c4d.Vector(0.25, 0.25, 0.25))
                for cx in range(cw+1):
                    lx = off_x + cx * cell_size
                    self.DrawLine(lx, off_y, lx, off_y+draw_h)
                for cy in range(ch+1):
                    ly = off_y + cy * cell_size
                    self.DrawLine(off_x, ly, off_x+draw_w, ly)

            # Ghost preview overlay for shape tools
            for (gx, gy, gcol) in self._ghost_pixels:
                if 0 <= gx < cw and 0 <= gy < ch:
                    gr, gg, gb, ga = gcol
                    if ga == 0:
                        # Erase ghost: show checkerboard color
                        checker = ((gx + gy) % 2 == 0)
                        cr, cg_, cb = CHECKER_A if checker else CHECKER_B
                        self.DrawSetPen(c4d.Vector(cr/255.0, cg_/255.0, cb/255.0))
                    else:
                        self.DrawSetPen(c4d.Vector(gr/255.0, gg/255.0, gb/255.0))
                    px = off_x + gx * cell_size
                    py = off_y + gy * cell_size
                    self.DrawRectangle(px, py, px+cell_size-1, py+cell_size-1)

        else:
            # View mode: composite canvas against UI background color, no grid
            for cy in range(ch):
                for cx in range(cw):
                    r, g, b, a = self._canvas.get(cx, cy)
                    t          = a / 255.0
                    dr = int(t*r + (1-t)*bg_r)
                    dg = int(t*g + (1-t)*bg_g)
                    db = int(t*b + (1-t)*bg_b)
                    px = off_x + cx * cell_size
                    py = off_y + cy * cell_size
                    self.DrawSetPen(c4d.Vector(dr/255.0, dg/255.0, db/255.0))
                    self.DrawRectangle(px, py, px+cell_size-1, py+cell_size-1)

        self._drawn_w = draw_w
        self._drawn_h = draw_h


# ---------------------------------------------------------------------------
# Signature Footer
# ---------------------------------------------------------------------------
_SIG_ICON_FULL_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAMCAYAAABr5z2BAAAAQklEQVR42mNgIBPU19f/B2EGuhoA"
    "00S2zWQZgE0TSQaRZQAhTbQxgJCmHiMjMAaxNcNqwJg6BhATQLicT7IB2MIJAG74zvGu0+RJAAAA"
    "AElFTkSuQmCC"
)


def _load_sig_icon():
    """Decode the signature icon Base64 -> CanvasState."""
    try:
        raw = base64.b64decode(_SIG_ICON_FULL_B64)
        pixels, w, h = _read_png_rgba(raw)
        cs = CanvasState(w, h)
        cs._px = pixels
        return cs
    except Exception:
        return None


class SignatureArea(c4d.gui.GeUserArea):

    URL     = "https://andreasriesener.com/"
    MAIL    = "mail@andreasriesener.com"
    T_LEFT  = "created by RiesiSir"
    T_RIGHT = "mail@andreasriesener.com"
    ICON_H  = 16   # target render height in pixels

    def __init__(self):
        self._sep_x  = 0
        self._icon   = _load_sig_icon()   # CanvasState or None

    def GetMinSize(self):
        return 300, 20

    def DrawMsg(self, x1, y1, x2, y2, msg):
        col = self.GetColorRGB(c4d.COLOR_BG)
        bg  = c4d.Vector(col["r"]/255.0, col["g"]/255.0, col["b"]/255.0)
        bg_r, bg_g, bg_b = col["r"], col["g"], col["b"]
        dim = c4d.Vector(0.45, 0.45, 0.45)

        self.DrawSetPen(bg)
        self.DrawRectangle(x1, y1, x2, y2)
        self.DrawSetTextCol(dim, bg)

        w_left  = self.DrawGetTextWidth(self.T_LEFT)
        w_right = self.DrawGetTextWidth(self.T_RIGHT)

        left_x  = x1 + 4
        right_x = x2 - w_right - 4
        text_y  = y1 + 3

        self.DrawText(self.T_LEFT,  left_x,  text_y)
        self.DrawText(self.T_RIGHT, right_x, text_y)

        # Draw icon centred between left text and right text
        mid_x = (left_x + w_left + right_x) // 2

        if self._icon is not None:
            ic = self._icon
            scale = self.ICON_H / float(ic.h)
            dst_w = max(1, int(ic.w * scale))
            dst_h = self.ICON_H
            icon_x = mid_x - dst_w // 2
            icon_y = y1 + (y2 - y1 - dst_h) // 2
            for dy in range(dst_h):
                for dx in range(dst_w):
                    sx = int(dx * ic.w / float(dst_w))
                    sy = int(dy * ic.h / float(dst_h))
                    r, g, b, a = ic.get(sx, sy)
                    t  = a / 255.0
                    dr = int(t * r + (1 - t) * bg_r)
                    dg = int(t * g + (1 - t) * bg_g)
                    db = int(t * b + (1 - t) * bg_b)
                    self.DrawSetPen(c4d.Vector(dr/255.0, dg/255.0, db/255.0))
                    self.DrawRectangle(icon_x + dx, icon_y + dy,
                                       icon_x + dx, icon_y + dy)
            self._sep_x = mid_x
        else:
            self._sep_x = mid_x

    def InputEvent(self, msg):
        if msg[c4d.BFM_INPUT_DEVICE] == c4d.BFM_INPUT_MOUSE:
            if msg[c4d.BFM_INPUT_CHANNEL] == c4d.BFM_INPUT_MOUSELEFT:
                mx = msg[c4d.BFM_INPUT_X]
                if mx < self._sep_x:
                    webbrowser.open(self.URL)
                else:
                    webbrowser.open("mailto:{}".format(self.MAIL))
        return True


STRIP_SIZES  = [64, 32, 24, 20, 16, 12, 8]  # large to small
STRIP_H      = 110  # fixed height - room for 64px icon + label
STRIP_PAD    = 6    # horizontal padding between columns
STRIP_LABEL  = 15   # pixels reserved below icon zone for size label
FONT_H       = 13   # C4D default font height in pixels (DrawText Y = top of glyph)
# Two dialog-context sizes: (icon_px, size_label)
CTX_VARIANTS = [(16, "16"), (12, "12")]

class PreviewStripUserArea(c4d.gui.GeUserArea):

    def __init__(self):
        self._canvas = None

    def SetCanvas(self, canvas):
        self._canvas = canvas
        self.Redraw()

    def GetMinSize(self):
        return 1, STRIP_H

    def _draw_icon(self, canvas, dst_w, dst_h, ox, oy, bg_r, bg_g, bg_b):
        """Nearest-neighbour blit of canvas scaled to dst_w x dst_h at (ox, oy)."""
        src_w, src_h = canvas.w, canvas.h
        for dy in range(dst_h):
            for dx in range(dst_w):
                sx = int(dx * src_w / float(dst_w))
                sy = int(dy * src_h / float(dst_h))
                r, g, b, a = canvas.get(sx, sy)
                t  = a / 255.0
                dr = int(t * r + (1 - t) * bg_r)
                dg = int(t * g + (1 - t) * bg_g)
                db = int(t * b + (1 - t) * bg_b)
                self.DrawSetPen(c4d.Vector(dr/255.0, dg/255.0, db/255.0))
                self.DrawRectangle(ox + dx, oy + dy, ox + dx, oy + dy)

    def DrawMsg(self, x1, y1, x2, y2, msg):
        self.OffScreenOn()
        self.SetClippingRegion(x1, y1, x2, y2)

        col              = self.GetColorRGB(c4d.COLOR_BG)
        bg_r, bg_g, bg_b = col["r"], col["g"], col["b"]
        bg_vec           = c4d.Vector(bg_r/255.0, bg_g/255.0, bg_b/255.0)
        txt_col          = self.GetColorRGB(c4d.COLOR_TEXT)
        tc_vec           = c4d.Vector(txt_col["r"]/255.0, txt_col["g"]/255.0, txt_col["b"]/255.0)
        dim_vec          = c4d.Vector(0.45, 0.45, 0.45)

        self.DrawSetPen(bg_vec)
        self.DrawRectangle(x1, y1, x2, y2)

        area_h      = y2 - y1
        icon_zone_h = area_h - STRIP_LABEL
        label_y     = y2 - STRIP_LABEL + 2
        mid_y       = y1 + icon_zone_h // 2

        if self._canvas is None:
            self.DrawSetTextCol(dim_vec, bg_vec)
            self.DrawText("Encode an image to see the preview strip.",
                          x1 + STRIP_PAD, mid_y - 5)
            return

        src_w, src_h = self._canvas.w, self._canvas.h

        # --- Icon strip (large -> small) ---
        cx = x1 + STRIP_PAD
        for sz in STRIP_SIZES:
            scale = sz / float(src_h)
            dst_w = max(1, int(src_w * scale))
            dst_h = max(1, int(src_h * scale))
            col_w = max(dst_w, 22)

            icon_x = cx + (col_w - dst_w) // 2
            icon_y = mid_y - dst_h // 2
            self._draw_icon(self._canvas, dst_w, dst_h, icon_x, icon_y,
                            bg_r, bg_g, bg_b)

            label   = "{}px".format(sz)
            label_x = cx + max(0, (col_w - len(label) * 5) // 2)
            self.DrawSetTextCol(dim_vec, bg_vec)
            self.DrawText(label, label_x, label_y)

            cx += col_w + STRIP_PAD

        # --- Vertical separator ---
        sep_x = cx + STRIP_PAD
        self.DrawSetPen(c4d.Vector(0.25, 0.25, 0.25))
        self.DrawLine(sep_x, y1 + 4, sep_x, y2 - 4)

        # --- Dialog-context variants ---
        # Layout: two rows centred in icon_zone.
        # Row 1: [icon] Label (Npx)  -- icon bottom-edge = text baseline
        # Row 2: [ icon  Button (Npx) ] frame
        # Rows are vertically centred together inside icon_zone.
        # Only the icon Y is adjusted for baseline; text stays at its natural row pos.
        ctx_x   = sep_x + STRIP_PAD * 2
        row_gap = 5
        btn_pad = 4

        for (icon_sz, sz_label) in CTX_VARIANTS:
            scale = icon_sz / float(src_h)
            dst_w = max(1, int(src_w * scale))
            dst_h = max(1, int(src_h * scale))

            # row_h = height of one row (text + some padding)
            row_h   = max(dst_h, FONT_H) + 4
            # total block height for centering
            total_h = row_h + row_gap + row_h + btn_pad * 2
            # top of block, centred in icon_zone
            block_y = y1 + (icon_zone_h - total_h) // 2

            # --- Row 1: [icon] Label (Npx) ---
            # Align icon bottom to row bottom, text centred in row.
            # Both share the same row bottom edge = block_y + row_h
            row1_bottom = block_y + row_h
            icon_y1 = row1_bottom - dst_h
            text_y1 = row1_bottom - FONT_H
            self._draw_icon(self._canvas, dst_w, dst_h, ctx_x, icon_y1,
                            bg_r, bg_g, bg_b)
            self.DrawSetTextCol(tc_vec, bg_vec)
            self.DrawText("Label ({})".format(sz_label),
                          ctx_x + dst_w + 4, text_y1)

            # --- Row 2: [ icon  Button (Npx) ] ---
            row2_y      = block_y + row_h + row_gap
            row2_bottom = row2_y + row_h
            icon_y2 = row2_bottom - dst_h
            text_y2 = row2_bottom - FONT_H

            btn_lbl = "Button ({})".format(sz_label)
            btn_w   = dst_w + 4 + len(btn_lbl) * 6 + btn_pad * 2
            btn_h   = row_h + btn_pad * 2

            # Button frame: C4D-style dark edge + slightly lighter fill
            edge_col = self.GetColorRGB(c4d.COLOR_EDGEDK)
            fill_col = self.GetColorRGB(c4d.COLOR_BG)
            edge_vec = c4d.Vector(edge_col["r"]/255.0, edge_col["g"]/255.0, edge_col["b"]/255.0)
            # Slightly lighter fill than bg
            fill_r = min(255, fill_col["r"] + 18)
            fill_g = min(255, fill_col["g"] + 18)
            fill_b = min(255, fill_col["b"] + 18)
            fill_vec = c4d.Vector(fill_r/255.0, fill_g/255.0, fill_b/255.0)

            self.DrawSetPen(edge_vec)
            self.DrawRectangle(ctx_x, row2_y, ctx_x + btn_w, row2_y + btn_h)
            self.DrawSetPen(fill_vec)
            self.DrawRectangle(ctx_x + 1, row2_y + 1,
                               ctx_x + btn_w - 1, row2_y + btn_h - 1)

            # Icon inside button -- composite against fill colour
            self._draw_icon(self._canvas, dst_w, dst_h,
                            ctx_x + btn_pad, icon_y2, fill_r, fill_g, fill_b)
            self.DrawSetTextCol(tc_vec, fill_vec)
            self.DrawText(btn_lbl, ctx_x + btn_pad + dst_w + 4, text_y2)

            # Variant label in label strip
            self.DrawSetTextCol(dim_vec, bg_vec)
            self.DrawText("{}px".format(icon_sz), ctx_x, label_y)

            ctx_x += btn_w + STRIP_PAD * 2

# ---------------------------------------------------------------------------
# New Canvas Size Dialog (modal)
# ---------------------------------------------------------------------------
class NewCanvasDialog(c4d.gui.GeDialog):

    def __init__(self):
        self.result_w = 0
        self.result_h = 0

    def CreateLayout(self):
        self.SetTitle("New Canvas")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0)
        self.GroupBorderSpace(10, 10, 10, 10)
        self.GroupSpace(4, 6)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 4, 1)
        self.AddStaticText(0, c4d.BFH_LEFT, initw=20, inith=0, name="W", borderstyle=0)
        self.AddEditNumberArrows(id=EDT_NEW_W, flags=c4d.BFH_LEFT, initw=70, inith=0)
        self.AddStaticText(0, c4d.BFH_LEFT, initw=20, inith=0, name="H", borderstyle=0)
        self.AddEditNumberArrows(id=EDT_NEW_H, flags=c4d.BFH_LEFT, initw=70, inith=0)
        self.GroupEnd()
        self.AddButton(id=BTN_NEW_CONFIRM, flags=c4d.BFH_CENTER, initw=100, inith=0, name="Create")
        self.GroupEnd()
        return super().CreateLayout()

    def InitValues(self):
        self.SetInt32(EDT_NEW_W, 32, min=1, max=512)
        self.SetInt32(EDT_NEW_H, 32, min=1, max=512)
        return super().InitValues()

    def Command(self, id, msg):
        if id == BTN_NEW_CONFIRM:
            self.result_w = self.GetInt32(EDT_NEW_W)
            self.result_h = self.GetInt32(EDT_NEW_H)
            self.Close()
        return super().Command(id, msg)

    def AskClose(self):
        return False


# ---------------------------------------------------------------------------
# Separate View Window - opened by View button, shows processed canvas
# ---------------------------------------------------------------------------
class ViewDialog(c4d.gui.GeDialog):

    def __init__(self):
        self._ua             = EditorUserArea()
        self._last_title     = ""
        self._on_view_request = None
        self._on_apply       = None
        self.Open(
            dlgtype=c4d.DLG_TYPE_ASYNC,
            pluginid=1059997,
            xpos=-2, ypos=-2,
            defaultw=460, defaulth=480
        )

    def CreateLayout(self):
        self.SetTitle("Preview")
        self.GroupBegin(id=PRV_VIEW_GRP, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, cols=1)
        self.GroupBorderSpace(8, 8, 8, 8)
        self.GroupSpace(spacex=4, spacey=4)

        # Filter row 1: Hard aliasing | threshold | Threshold  ····  Apply to Canvas
        self.GroupBegin(id=PRV_GRP_FILTERS, flags=c4d.BFH_SCALEFIT, cols=5)
        self.AddCheckbox(id=PRV_CHK_AA, flags=c4d.BFH_LEFT, initw=0, inith=0, name="Hard aliasing")
        self.AddEditNumberArrows(id=PRV_EDT_THRESHOLD, flags=c4d.BFH_LEFT, initw=55, inith=0)
        self.AddStaticText(id=0, flags=c4d.BFH_LEFT, initw=0, inith=0, name="Threshold", borderstyle=0)
        self.AddStaticText(id=0, flags=c4d.BFH_SCALEFIT, initw=0, inith=0, name="", borderstyle=0)
        self.AddButton(id=PRV_BTN_APPLY, flags=c4d.BFH_RIGHT, initw=140, inith=0, name="Apply to Canvas")
        self.GroupEnd()

        # Filter row 2: Resize checkbox | W | W label | H | H label | Prop.
        self.GroupBegin(id=PRV_GRP_FILTERS + 1, flags=c4d.BFH_SCALEFIT, cols=6)
        self.AddCheckbox(id=PRV_CHK_RESIZE, flags=c4d.BFH_LEFT, initw=0, inith=0, name="Resize:")
        self.AddEditNumberArrows(id=PRV_EDT_W, flags=c4d.BFH_LEFT, initw=55, inith=0)
        self.AddStaticText(id=0, flags=c4d.BFH_LEFT, initw=20, inith=0, name="W", borderstyle=0)
        self.AddEditNumberArrows(id=PRV_EDT_H, flags=c4d.BFH_LEFT, initw=55, inith=0)
        self.AddStaticText(id=0, flags=c4d.BFH_LEFT, initw=20, inith=0, name="H", borderstyle=0)
        self.AddCheckbox(id=PRV_CHK_PROP, flags=c4d.BFH_LEFT, initw=0, inith=0, name="Proportional")
        self.GroupEnd()

        self.AddSeparatorH(0, c4d.BFH_SCALEFIT)

        self.AddUserArea(id=PRV_USER_AREA + 100,
                         flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                         initw=440, inith=440)
        self.AttachUserArea(self._ua, PRV_USER_AREA + 100)
        self.GroupEnd()
        return super().CreateLayout()

    def InitValues(self):
        self._ua.SetDrawMode(False)
        self.SetBool(PRV_CHK_AA,         False)
        self.SetInt32(PRV_EDT_THRESHOLD,  13, min=0, max=100)
        self.SetBool(PRV_CHK_RESIZE,      False)
        self.SetInt32(PRV_EDT_W,          32, min=1, max=8192)
        self.SetInt32(PRV_EDT_H,          32, min=1, max=8192)
        self.SetBool(PRV_CHK_PROP,        True)
        self._vdlg_orig_w = 0
        self._vdlg_orig_h = 0
        self._updating    = False
        self.SetTimer(150)
        return super().InitValues()

    def _get_filter_settings(self):
        return {
            "use_aa":    self.GetBool(PRV_CHK_AA),
            "threshold": int(self.GetInt32(PRV_EDT_THRESHOLD) / 100.0 * 255),
            "use_resize": self.GetBool(PRV_CHK_RESIZE),
            "w":         self.GetInt32(PRV_EDT_W),
            "h":         self.GetInt32(PRV_EDT_H),
        }

    def Command(self, id, msg):
        if getattr(self, "_updating", False):
            return super().Command(id, msg)
        if id in (PRV_CHK_AA, PRV_CHK_RESIZE, PRV_EDT_THRESHOLD):
            if id == PRV_CHK_RESIZE:
                en = self.GetBool(PRV_CHK_RESIZE)
                self.Enable(PRV_EDT_W, en)
                self.Enable(PRV_EDT_H, en)
                self.Enable(PRV_CHK_PROP, en)
            if self._on_view_request:
                self._on_view_request()
        elif id in (PRV_EDT_W, PRV_EDT_H):
            if self.GetBool(PRV_CHK_PROP) and self._vdlg_orig_w > 0 and self._vdlg_orig_h > 0:
                ratio = self._vdlg_orig_w / float(self._vdlg_orig_h)
                if id == PRV_EDT_W:
                    w = self.GetInt32(PRV_EDT_W)
                    self.SetInt32(PRV_EDT_H, max(1, int(round(w / ratio))), min=1, max=8192)
                else:
                    h = self.GetInt32(PRV_EDT_H)
                    self.SetInt32(PRV_EDT_W, max(1, int(round(h * ratio))), min=1, max=8192)
            if self._on_view_request:
                self._on_view_request()
        elif id == PRV_BTN_APPLY:
            if self._on_apply:
                f = self._get_filter_settings()
                self._on_apply(f)
        return super().Command(id, msg)

    def SetViewRequestCallback(self, fn):
        self._on_view_request = fn

    def SetApplyCallback(self, fn):
        self._on_apply = fn

    def SyncSize(self, w, h):
        self._vdlg_orig_w = w
        self._vdlg_orig_h = h
        try:
            self.SetInt32(PRV_EDT_W, w, min=1, max=8192)
            self.SetInt32(PRV_EDT_H, h, min=1, max=8192)
        except Exception:
            pass

    def UpdateCanvas(self, canvas, bg_r=50, bg_g=50, bg_b=50):
        flat = make_flat_preview(canvas.to_bitmap(), bg_r, bg_g, bg_b)
        self._ua._flat_bmp = flat
        self._ua._orig_w   = canvas.w
        self._ua._orig_h   = canvas.h
        self._ua.SetDrawMode(False)
        self._ua.Redraw()

    def UpdateFlat(self, flat_bmp, orig_w, orig_h):
        self._ua._flat_bmp = flat_bmp
        self._ua._orig_w   = orig_w
        self._ua._orig_h   = orig_h
        self._ua.SetDrawMode(False)
        self._ua.Redraw()

    def Timer(self, msg):
        w = self._ua._orig_w if hasattr(self._ua, "_orig_w") else 0
        h = self._ua._orig_h if hasattr(self._ua, "_orig_h") else 0
        if w > 0:
            dw, dh = self._ua.GetDrawnSize()
            if dw > 0:
                title = "View  |  {}x{} px  |  C4D: initw={} inith={}".format(
                    dw, dh, dw, dh)
            else:
                title = "View  |  {}x{} px".format(w, h)
        else:
            title = "View"
        if title != self._last_title:
            self._last_title = title
            self.SetTitle(title)

    def KeyboardInput(self, key, qualifier):
        ctrl = bool(qualifier & c4d.QUALIFIER_CTRL)
        shft = bool(qualifier & c4d.QUALIFIER_SHIFT)
        if ctrl and not shft and key == ord("Z"):
            if self._ua.Undo():
                self._orig_canvas = self._ua._canvas
                if self._view_dlg and self._view_dlg.IsOpen():
                    self._view_dlg.UpdateCanvas(self._orig_canvas)
            return True
        if ctrl and (key == ord("Y") or (shft and key == ord("Z"))):
            if self._ua.Redo():
                self._orig_canvas = self._ua._canvas
                if self._view_dlg and self._view_dlg.IsOpen():
                    self._view_dlg.UpdateCanvas(self._orig_canvas)
            return True
        return False

    def AskClose(self):
        self.SetTimer(0)
        return False


# ---------------------------------------------------------------------------
# Preview / Editor Dialog
# ---------------------------------------------------------------------------
class PreviewDialog(c4d.gui.GeDialog):

    def __init__(self):
        self._ua              = EditorUserArea()
        self._last_title      = ""
        self._draw_mode       = True  # always start in draw mode
        self._tool            = EditorUserArea.TOOL_PENCIL
        self._on_view_request = None
        self._edit_canvas     = None
        self._orig_canvas     = None
        self._last_processed  = None
        self._view_dlg        = None  # separate View window
        self._on_external_change = None
        self.Open(
            dlgtype=c4d.DLG_TYPE_ASYNC,
            pluginid=1059996,
            xpos=-2, ypos=-2,
            defaultw=460, defaulth=500
        )

    def SetViewRequestCallback(self, fn):
        self._on_view_request = fn

    def SetExternalChangeCallback(self, fn):
        self._on_external_change = fn

    def _do_apply_from_view(self):
        """Called when Apply to Canvas is pressed in ViewDialog."""
        if not self._view_dlg or not self._view_dlg.IsOpen():
            return
        canvas = self._ua._canvas
        if not canvas:
            return
        use_resize  = self._view_dlg.GetBool(PRV_CHK_RESIZE)
        use_aa      = self._view_dlg.GetBool(PRV_CHK_AA)
        threshold   = int(self._view_dlg.GetInt32(PRV_EDT_THRESHOLD) / 100.0 * 255)
        target_w    = self._view_dlg.GetInt32(PRV_EDT_W)
        target_h    = self._view_dlg.GetInt32(PRV_EDT_H)
        if not use_resize and not use_aa:
            return
        self._ua.PushUndo()
        result = canvas
        if use_resize and (target_w != canvas.w or target_h != canvas.h):
            scaled = CanvasState(target_w, target_h)
            for dy in range(target_h):
                for dx in range(target_w):
                    sx = int(dx * canvas.w / float(target_w))
                    sy = int(dy * canvas.h / float(target_h))
                    scaled.set(dx, dy, canvas.get(sx, sy))
            result = scaled
        if use_aa:
            aliased = CanvasState(result.w, result.h)
            for y in range(result.h):
                for x in range(result.w):
                    r, g, b, a = result.get(x, y)
                    new_a = 255 if a >= threshold else 0
                    if new_a == 0:
                        r, g, b = 0, 0, 0
                    aliased.set(x, y, (r, g, b, new_a))
            result = aliased
        self.LoadCanvasFromState(result)
        if self._on_external_change:
            self._on_external_change(result)

    def CreateLayout(self):
        self.SetTitle("Editor")

        self.GroupBegin(id=PRV_GRP_MAIN, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, cols=1)
        self.GroupBorderSpace(8, 8, 8, 8)
        self.GroupSpace(spacex=4, spacey=4)

        # Toolbar row 1: Preview | Clear Canvas | Auto Crop | Fill | Color
        self.GroupBegin(id=PRV_GRP_TOOLBAR, flags=c4d.BFH_SCALEFIT, cols=6)
        self.AddButton(id=BTN_MODE_VIEW,  flags=c4d.BFH_LEFT, initw=70,  inith=0, name="Preview")
        self.AddSeparatorV(inith=0)
        self.AddButton(id=BTN_TOOL_CLEAR, flags=c4d.BFH_LEFT, initw=100, inith=0, name="Clear Canvas")
        self.AddButton(id=BTN_AUTO_CROP,  flags=c4d.BFH_LEFT, initw=90,  inith=0, name="Auto Crop")
        self.AddButton(id=BTN_TOOL_FILL,  flags=c4d.BFH_LEFT, initw=50,  inith=0, name="Fill")
        self.AddColorField(id=CLR_FOREGROUND, flags=c4d.BFH_LEFT, initw=40, inith=14,
                           colorflags=0)
        self.GroupEnd()

        # Toolbar row 2: Pencil | Line | Rectangle | Circle | [x] Filled Shape
        self.GroupBegin(id=PRV_GRP_TOOLBAR + 1, flags=c4d.BFH_SCALEFIT, cols=6)
        self.AddButton(id=BTN_TOOL_PENCIL, flags=c4d.BFH_LEFT, initw=65, inith=0, name="Pencil")
        self.AddButton(id=BTN_TOOL_LINE,   flags=c4d.BFH_LEFT, initw=55, inith=0, name="Line")
        self.AddButton(id=BTN_TOOL_RECT,   flags=c4d.BFH_LEFT, initw=90, inith=0, name="Rectangle")
        self.AddButton(id=BTN_TOOL_CIRCLE, flags=c4d.BFH_LEFT, initw=65, inith=0, name="Circle")
        self.AddCheckbox(id=CHK_FILLED_SHAPE, flags=c4d.BFH_LEFT, initw=0, inith=0, name="Filled Shape")
        self.GroupEnd()

        self.AddSeparatorH(0, c4d.BFH_SCALEFIT)

        self.AddUserArea(id=PRV_USER_AREA, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                         initw=400, inith=400)
        self.AttachUserArea(self._ua, PRV_USER_AREA)

        self.GroupEnd()
        return super().CreateLayout()

    def InitValues(self):
        self.SetColorField(CLR_FOREGROUND,
                           c4d.Vector(1.0, 1.0, 1.0), 1.0, 1.0,
                           c4d.DR_COLORFIELD_NO_BRIGHTNESS)
        self.SetBool(CHK_FILLED_SHAPE, False)
        self._prv_orig_w = 0
        self._prv_orig_h = 0
        self._ua.SetChangeCallback(self._on_canvas_change)
        self._ua.SetDrawMode(True)
        self._update_toolbar_state()
        self.SetTimer(150)
        return super().InitValues()

    def _update_toolbar_state(self):
        in_draw = self._draw_mode
        self.Enable(BTN_TOOL_FILL,   in_draw)
        self.Enable(BTN_TOOL_CLEAR,  in_draw)
        self.Enable(BTN_AUTO_CROP,   in_draw)
        self.Enable(BTN_TOOL_PENCIL, in_draw)
        self.Enable(BTN_TOOL_LINE,   in_draw)
        self.Enable(BTN_TOOL_RECT,   in_draw)
        self.Enable(BTN_TOOL_CIRCLE, in_draw)
        self.Enable(CHK_FILLED_SHAPE,in_draw)
        self.Enable(CLR_FOREGROUND,  in_draw)

    def _on_apply_from_view(self, f):
        canvas = self._ua._canvas
        if not canvas:
            return
        self._ua.PushUndo()
        result = canvas
        if f["use_resize"] and (f["w"] != canvas.w or f["h"] != canvas.h):
            scaled = CanvasState(f["w"], f["h"])
            for dy in range(f["h"]):
                for dx in range(f["w"]):
                    sx = int(dx * canvas.w / float(f["w"]))
                    sy = int(dy * canvas.h / float(f["h"]))
                    scaled.set(dx, dy, canvas.get(sx, sy))
            result = scaled
        if f["use_aa"]:
            aliased = CanvasState(result.w, result.h)
            for y in range(result.h):
                for x in range(result.w):
                    r, g, b, a = result.get(x, y)
                    new_a = 255 if a >= f["threshold"] else 0
                    if new_a == 0:
                        r, g, b = 0, 0, 0
                    aliased.set(x, y, (r, g, b, new_a))
            result = aliased
        self.LoadCanvasFromState(result)
        if self._on_external_change:
            self._on_external_change(result)

    def _on_canvas_change(self):
        self._orig_canvas = self._ua._canvas
        if self._on_external_change:
            self._on_external_change(self._orig_canvas)
        if self._view_dlg and self._view_dlg.IsOpen() and self._orig_canvas:
            self._view_dlg.UpdateCanvas(self._orig_canvas)

    def UpdateImage(self, flat_bmp, orig_w, orig_h):
        # Push to view window if open; draw canvas stays untouched
        if self._view_dlg and self._view_dlg.IsOpen():
            self._view_dlg.UpdateFlat(flat_bmp, orig_w, orig_h)

    def UpdateViewFromCanvas(self, processed_canvas):
        # Store for Apply; push to separate view window if open
        self._last_processed = processed_canvas
        if self._view_dlg and self._view_dlg.IsOpen():
            self._view_dlg.UpdateCanvas(processed_canvas)

    def LoadCanvasFromState(self, canvas):
        self._orig_canvas    = canvas
        self._last_processed = None
        self._ua._canvas     = canvas
        self._ua._flat_bmp   = None
        self._draw_mode      = True
        self._ua.SetDrawMode(True)
        self._update_toolbar_state()
        self._ua.Redraw()
        # Sync filter W/H fields to canvas size
        self._prv_orig_w = canvas.w
        self._prv_orig_h = canvas.h
        try:
            self.SetInt32(PRV_EDT_W, canvas.w, min=1, max=8192)
            self.SetInt32(PRV_EDT_H, canvas.h, min=1, max=8192)
        except Exception:
            pass

    def ApplyProcessed(self):
        """Permanently replace _orig_canvas with the last processed view."""
        if self._last_processed is not None:
            self._orig_canvas    = self._last_processed
            self._last_processed = None
            return self._orig_canvas
        return None

    def GetOrigCanvas(self):
        return self._orig_canvas

    def GetCanvas(self):
        return self._ua._canvas

    def Command(self, id, msg):

        if id == BTN_MODE_VIEW:
            if self._view_dlg is None or not self._view_dlg.IsOpen():
                self._view_dlg = ViewDialog()
                self._view_dlg.SetViewRequestCallback(self._on_view_request)
                self._view_dlg.SetApplyCallback(self._on_apply_from_view)
                if self._orig_canvas:
                    self._view_dlg.SyncSize(self._orig_canvas.w, self._orig_canvas.h)
            if self._orig_canvas and self._on_view_request:
                self._on_view_request()
            elif self._orig_canvas:
                self._view_dlg.UpdateCanvas(self._orig_canvas)

            self._tool = EditorUserArea.TOOL_PENCIL
            self._ua.SetTool(self._tool)
            self._update_toolbar_state()
            self._ua.Redraw()

        elif id == BTN_TOOL_FILL:
            self._tool = EditorUserArea.TOOL_FILL
            self._ua.SetTool(self._tool)

        elif id == BTN_TOOL_PENCIL:
            self._tool = EditorUserArea.TOOL_PENCIL
            self._ua.SetTool(self._tool)

        elif id == BTN_TOOL_LINE:
            self._tool = EditorUserArea.TOOL_LINE
            self._ua.SetTool(self._tool)

        elif id == BTN_TOOL_RECT:
            self._tool = EditorUserArea.TOOL_RECT
            self._ua.SetTool(self._tool)

        elif id == BTN_TOOL_CIRCLE:
            self._tool = EditorUserArea.TOOL_CIRCLE
            self._ua.SetTool(self._tool)

        elif id == CHK_FILLED_SHAPE:
            self._ua.SetFilledShape(self.GetBool(CHK_FILLED_SHAPE))

        elif id == BTN_TOOL_CLEAR:
            canvas = self._ua._canvas
            if canvas:
                self._ua.PushUndo()
                canvas.clear()
                self._ua.Redraw()

        elif id == BTN_AUTO_CROP:
            canvas = self._ua._canvas
            if canvas:
                self._ua.PushUndo()
                cropped = canvas.auto_crop()
                self._ua._canvas  = cropped
                self._orig_canvas = cropped
                self._ua.Redraw()
                # Sync ViewDialog W/H WITHOUT triggering a filter-change render
                if self._view_dlg and self._view_dlg.IsOpen():
                    self._view_dlg._updating = True
                    try:
                        self._view_dlg.SyncSize(cropped.w, cropped.h)
                    finally:
                        self._view_dlg._updating = False
                    # Now refresh the view with the new (unchanged) filter settings
                    self._view_dlg.UpdateCanvas(cropped)
                # Notify Base64Dlg so _orig_w/_orig_h stay in sync
                if self._on_external_change:
                    self._on_external_change(cropped)

        elif id == CLR_FOREGROUND:
            col = self.GetColorField(CLR_FOREGROUND)
            if col:
                r = int(col["color"].x * 255)
                g = int(col["color"].y * 255)
                b = int(col["color"].z * 255)
                self._ua.SetForegroundColor(r, g, b, 255)
                self._tool = EditorUserArea.TOOL_PENCIL
                self._ua.SetTool(self._tool)


        return super().Command(id, msg)

    def Timer(self, msg):
        canvas  = self._ua._canvas
        draw_w, draw_h = self._ua.GetDrawnSize()
        if self._draw_mode and canvas:
            u = self._ua.GetUndoCount()
            r = self._ua.GetRedoCount()
            title = "Editor  |  {}x{} px  |  Undo:{}  Redo:{}  |  C4D: initw={} inith={}".format(
                canvas.w, canvas.h, u, r, canvas.w, canvas.h)
        elif draw_w > 0:
            title = "View  |  {}x{} px  |  C4D: initw={} inith={}".format(
                draw_w, draw_h, draw_w, draw_h)
        else:
            title = "Preview"
        if title != self._last_title:
            self._last_title = title
            self.SetTitle(title)

    def Message(self, msg, result):
        if msg.GetId() == c4d.BFM_INPUT:
            if msg.GetInt32(c4d.BFM_INPUT_DEVICE) == c4d.BFM_INPUT_KEYBOARD:
                qual = msg.GetInt32(c4d.BFM_INPUT_QUALIFIER)
                ctrl = bool(qual & c4d.QUALIFIER_CTRL)
                shft = bool(qual & c4d.QUALIFIER_SHIFT)
                ch   = msg.GetInt32(c4d.BFM_INPUT_CHANNEL)
                if ctrl and not shft and ch == ord("Z"):
                    if self._ua.Undo():
                        self._orig_canvas = self._ua._canvas
                        if self._view_dlg and self._view_dlg.IsOpen():
                            self._view_dlg.UpdateCanvas(self._orig_canvas)
                    return True
                if ctrl and (ch == ord("Y") or (shft and ch == ord("Z"))):
                    if self._ua.Redo():
                        self._orig_canvas = self._ua._canvas
                        if self._view_dlg and self._view_dlg.IsOpen():
                            self._view_dlg.UpdateCanvas(self._orig_canvas)
                    return True
        return super().Message(msg, result)

    def AskClose(self):
        self.SetTimer(0)
        return False


# ---------------------------------------------------------------------------
# Main Dialog
# ---------------------------------------------------------------------------
class Base64Dlg(c4d.gui.GeDialog):

    def __init__(self):
        self._path     = ""
        self._result   = ""
        self._orig_w   = 0
        self._orig_h   = 0
        self._preview  = None
        self._strip_ua = PreviewStripUserArea()
        self._sig_area = SignatureArea()

    def CreateLayout(self):
        self.SetTitle("Base64 Image Tool  v0.4.7")

        self.GroupBegin(id=GRP_MAIN, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, cols=1)
        self.GroupSpace(spacex=6, spacey=6)
        self.GroupBorderSpace(8, 8, 8, 8)

        # --- File section ---
        self.GroupBegin(id=GRP_FILE, flags=c4d.BFH_SCALEFIT, cols=1)
        self.GroupBorder(c4d.BORDER_GROUP_IN)
        self.GroupBorderSpace(6, 6, 6, 6)
        self.GroupSpace(spacex=4, spacey=4)

        self.GroupBegin(id=GRP_EDITOR_BTNS, flags=c4d.BFH_SCALEFIT, cols=5)
        self.AddButton(id=BTN_NEW_CANVAS,  flags=c4d.BFH_LEFT,  initw=130, inith=0, name="New Canvas...")
        self.AddStaticText(id=0, flags=c4d.BFH_SCALEFIT, initw=0, inith=0, name="", borderstyle=0)
        self.AddButton(id=BTN_LOAD,        flags=c4d.BFH_RIGHT, initw=100, inith=0, name="Open...")
        self.AddButton(id=BTN_CLIP_LOAD,   flags=c4d.BFH_RIGHT, initw=140, inith=0, name="From Clipboard")
        self.AddButton(id=BTN_SAVE_PNG,    flags=c4d.BFH_RIGHT, initw=120, inith=0, name="Save as PNG...")
        self.GroupEnd()

        self.GroupEnd()  # GRP_FILE

        # --- Result section ---
        self.GroupBegin(id=GRP_RES, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, cols=1)
        self.GroupBorder(c4d.BORDER_GROUP_IN)
        self.GroupBorderSpace(6, 4, 6, 6)
        self.GroupSpace(spacex=4, spacey=4)

        self.AddStaticText(id=TXT_STATUS, flags=c4d.BFH_SCALEFIT, initw=0, inith=0, name="", borderstyle=0)
        self.AddMultiLineEditText(id=TXT_RESULT, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                                  initw=0, inith=80,
                                  style=c4d.DR_MULTILINE_READONLY | c4d.DR_MULTILINE_MONOSPACED)

        # Encode + Copy + Clear in one row
        self.GroupBegin(id=GRP_BTNS, flags=c4d.BFH_SCALEFIT, cols=3)
        self.GroupSpace(spacex=4, spacey=0)
        self.AddButton(id=BTN_ENCODE, flags=c4d.BFH_SCALEFIT, initw=200, inith=0, name="Encode  ->  Base64")
        self.AddButton(id=BTN_CLEAR,  flags=c4d.BFH_SCALEFIT, initw=80,  inith=0, name="Clear")
        self.GroupEnd()
        self.AddCheckbox(id=CHK_CHUNKS, flags=c4d.BFH_LEFT, initw=0, inith=0, name="Python chunks format")

        self.GroupEnd()  # GRP_RES

        # --- Tabs: Encode output / Decode input ---
        self.TabGroupBegin(id=GRP_TABS, flags=c4d.BFH_SCALEFIT)

        # Encode tab
        self.GroupBegin(id=GRP_ENCODE_PAGE, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                        cols=1, title="Encode")
        self.GroupBorderSpace(4, 4, 4, 4)
        self.GroupSpace(spacex=0, spacey=4)
        self.AddStaticText(id=0, flags=c4d.BFH_LEFT, initw=0, inith=0,
                           name="Use Encode -> Base64 above, then Copy to Clipboard.", borderstyle=0)
        self.AddUserArea(id=PRV_STRIP_UA,
                         flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                         initw=0, inith=STRIP_H)
        self.AttachUserArea(self._strip_ua, PRV_STRIP_UA)
        self.GroupEnd()

        # Decode tab
        self.GroupBegin(id=GRP_DECODE_PAGE, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                        cols=1, title="Decode / Import")
        self.GroupBorderSpace(4, 4, 4, 4)
        self.GroupSpace(spacex=4, spacey=4)
        self.AddStaticText(id=0, flags=c4d.BFH_LEFT, initw=0, inith=0,
                           name="Paste Base64 Data URL, then click Import:", borderstyle=0)
        self.AddMultiLineEditText(id=EDT_DECODE_INPUT, flags=c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                                  initw=0, inith=60,
                                  style=c4d.DR_MULTILINE_MONOSPACED)
        self.AddButton(id=BTN_DECODE, flags=c4d.BFH_CENTER, initw=180, inith=0,
                       name="Import into Editor")
        self.GroupEnd()

        self.GroupEnd()  # TabGroup
        self.GroupEnd()  # GRP_MAIN

        # Signature footer
        self.AddSeparatorH(0, c4d.BFH_SCALEFIT)
        if self.AddUserArea(SIG_AREA, c4d.BFH_SCALEFIT, 0, 20):
            self.AttachUserArea(self._sig_area, SIG_AREA)

        return super().CreateLayout()

    def InitValues(self):
        self.Enable(BTN_APPLY,         False)
        self.Enable(BTN_SAVE_PNG,      False)
        self.SetBool(CHK_AA,           False)
        self.SetBool(CHK_CHUNKS,       True)
        self.SetInt32(EDT_THRESHOLD,   13, min=0, max=100)
        self.SetBool(CHK_RESIZE,       False)
        self.SetBool(CHK_PROPORTIONAL, True)
        self.SetInt32(EDT_WIDTH,       32, min=1, max=8192)
        self.SetInt32(EDT_HEIGHT,      32, min=1, max=8192)
        self._update_resize_enable()
        return super().InitValues()

    def _ensure_preview(self):
        if self._preview is None or not self._preview.IsOpen():
            self._preview = PreviewDialog()
            self._preview.SetViewRequestCallback(self._push_canvas_view)
            self._preview.SetExternalChangeCallback(self._on_canvas_size_change)

    def _on_canvas_size_change(self, canvas):
        if canvas:
            self._orig_w = canvas.w
            self._orig_h = canvas.h

    def _push_canvas_view(self):
        if not self._preview:
            return
        canvas = self._preview._ua._canvas or self._preview.GetOrigCanvas()
        if not canvas:
            return

        vdlg = self._preview._view_dlg if self._preview else None
        if not vdlg or not vdlg.IsOpen():
            return
        f = vdlg._get_filter_settings()
        use_resize     = f["use_resize"]
        use_hard_alias = f["use_aa"]
        target_w       = f["w"]
        target_h       = f["h"]
        threshold      = f["threshold"]

        result = canvas

        if use_resize and (target_w != canvas.w or target_h != canvas.h):
            scaled = CanvasState(target_w, target_h)
            for dy in range(target_h):
                for dx in range(target_w):
                    sx = int(dx * canvas.w / float(target_w))
                    sy = int(dy * canvas.h / float(target_h))
                    scaled.set(dx, dy, canvas.get(sx, sy))
            result = scaled

        if use_hard_alias:
            aliased = CanvasState(result.w, result.h)
            for y in range(result.h):
                for x in range(result.w):
                    r, g, b, a = result.get(x, y)
                    new_a = 255 if a >= threshold else 0
                    if new_a == 0:
                        r, g, b = 0, 0, 0
                    aliased.set(x, y, (r, g, b, new_a))
            result = aliased

        # Store for Apply AND push to ViewDialog
        self._preview._last_processed = result
        if self._preview._view_dlg and self._preview._view_dlg.IsOpen():
            self._preview._view_dlg.UpdateCanvas(result)

    def _update_resize_enable(self):
        enabled = self.GetBool(CHK_RESIZE)
        self.Enable(EDT_WIDTH,        enabled)
        self.Enable(EDT_HEIGHT,       enabled)
        self.Enable(CHK_PROPORTIONAL, enabled)

    def _update_proportional(self, changed_id):
        if not self.GetBool(CHK_PROPORTIONAL) or self._orig_w == 0 or self._orig_h == 0:
            return
        ratio = float(self._orig_w) / float(self._orig_h)
        if changed_id == EDT_WIDTH:
            w = self.GetInt32(EDT_WIDTH)
            self.SetInt32(EDT_HEIGHT, max(1, int(round(w / ratio))), min=1, max=8192)
        elif changed_id == EDT_HEIGHT:
            h = self.GetInt32(EDT_HEIGHT)
            self.SetInt32(EDT_WIDTH, max(1, int(round(h * ratio))), min=1, max=8192)

    def _push_to_preview(self):
        if self._preview is None or not self._path:
            return
        use_resize     = self.GetBool(CHK_RESIZE)
        use_hard_alias = self.GetBool(CHK_AA)
        target_w       = self.GetInt32(EDT_WIDTH)
        target_h       = self.GetInt32(EDT_HEIGHT)
        threshold      = int(self.GetInt32(EDT_THRESHOLD) / 100.0 * 255)
        bmp  = process_bitmap(self._path, use_resize, target_w, target_h, use_hard_alias, threshold)
        flat = make_flat_preview(bmp, 50, 50, 50)
        self._preview.UpdateImage(flat, bmp.GetBw(), bmp.GetBh())

    def _set_status(self, text):
        self.SetString(TXT_STATUS, text)

    def _encode_canvas(self):
        """Encode the current canvas as-is. Use Apply to Canvas first for resize/alias."""
        canvas = self._preview.GetOrigCanvas() if self._preview else None
        if not canvas:
            self._set_status("No canvas to encode.")
            return
        try:
            use_chunks = self.GetBool(CHK_CHUNKS)
            data_url, b64, raw = canvas_to_data_url(canvas)
            self._result = data_url
            kb = len(raw) / 1024.0
            self._set_status("OK  |  {:.1f} KB  |  {} chars  |  {}x{} px".format(
                kb, len(b64), canvas.w, canvas.h))
            display = format_base64_python(b64) if use_chunks else b64
            self.SetString(TXT_RESULT, display)
            self._strip_ua.SetCanvas(canvas)
        except Exception as e:
            self._set_status("Error encoding canvas: {}".format(e))

    def Command(self, id, msg):

        if id == BTN_LOAD:
            path = c4d.storage.LoadDialog(
                title="Select Image", flags=c4d.FILESELECT_LOAD,
                force_suffix="", def_path="", def_file=""
            )
            if path:
                self._path   = path
                self._result = ""
                w, h = get_image_size(path)
                self._orig_w = w
                self._orig_h = h
                self.SetString(TXT_RESULT,    "")
                self.SetString(TXT_ORIG_SIZE, "  Orig: {}x{}".format(w, h))
                self.SetInt32(EDT_WIDTH,  w, min=1, max=8192)
                self.SetInt32(EDT_HEIGHT, h, min=1, max=8192)
                # Auto-load into editor
                self._ensure_preview()
                threshold_val  = int(self.GetInt32(EDT_THRESHOLD) / 100.0 * 255)
                use_resize     = self.GetBool(CHK_RESIZE)
                use_hard_alias = self.GetBool(CHK_AA)
                target_w       = self.GetInt32(EDT_WIDTH)
                target_h       = self.GetInt32(EDT_HEIGHT)
                auto_bmp    = process_bitmap(path, use_resize, target_w, target_h,
                                             use_hard_alias, threshold_val)
                auto_canvas = CanvasState.from_bitmap(auto_bmp)
                self._preview.LoadCanvasFromState(auto_canvas)
                self._orig_w = auto_canvas.w
                self._orig_h = auto_canvas.h
                self.SetInt32(EDT_WIDTH,  auto_canvas.w, min=1, max=8192)
                self.SetInt32(EDT_HEIGHT, auto_canvas.h, min=1, max=8192)
                self.SetString(TXT_ORIG_SIZE, "  Canvas: {}x{}".format(
                    auto_canvas.w, auto_canvas.h))
                self.Enable(BTN_APPLY,    True)
                self.Enable(BTN_SAVE_PNG, True)
                self._set_status("Loaded {}x{} px into editor.".format(
                    auto_canvas.w, auto_canvas.h))
                self._push_to_preview()

        elif id == BTN_CLIP_LOAD:
            try:
                tmp_path = load_image_from_clipboard()
                bmp = c4d.bitmaps.BaseBitmap()
                result, _ = bmp.InitWith(tmp_path)
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                if result != c4d.IMAGERESULT_OK:
                    self._set_status("Could not load clipboard image.")
                    return True
                canvas = CanvasState.from_bitmap(bmp)
                self._ensure_preview()
                self._preview.LoadCanvasFromState(canvas)
                self._orig_w = canvas.w
                self._orig_h = canvas.h
                self.SetInt32(EDT_WIDTH,  canvas.w, min=1, max=8192)
                self.SetInt32(EDT_HEIGHT, canvas.h, min=1, max=8192)
                self.SetString(TXT_ORIG_SIZE, "  Canvas: {}x{}".format(canvas.w, canvas.h))
                self.Enable(BTN_APPLY,    True)
                self.Enable(BTN_SAVE_PNG, True)
                self._set_status("Loaded {}x{} px from clipboard.".format(canvas.w, canvas.h))
                self._push_to_preview()
            except Exception as e:
                self._set_status("Clipboard error: {}".format(e))

        elif id == BTN_NEW_CANVAS:
            dlg = NewCanvasDialog()
            dlg.Open(dlgtype=c4d.DLG_TYPE_MODAL, xpos=-2, ypos=-2, defaultw=260, defaulth=100)
            if dlg.result_w > 0 and dlg.result_h > 0:
                canvas = CanvasState(dlg.result_w, dlg.result_h, fill=(0, 0, 0, 0))
                self._ensure_preview()
                self._preview.LoadCanvasFromState(canvas)
                # Set as base size for proportional resize
                self._orig_w = dlg.result_w
                self._orig_h = dlg.result_h
                self.SetInt32(EDT_WIDTH,  dlg.result_w, min=1, max=8192)
                self.SetInt32(EDT_HEIGHT, dlg.result_h, min=1, max=8192)
                self.SetString(TXT_ORIG_SIZE, "  Canvas: {}x{}".format(dlg.result_w, dlg.result_h))
                self.Enable(BTN_APPLY,    True)
                self.Enable(BTN_SAVE_PNG, True)
                self._set_status("New canvas {}x{} px - draw in the Preview window.".format(
                    dlg.result_w, dlg.result_h))

        elif id == BTN_DECODE:
            data_url = self.GetString(EDT_DECODE_INPUT).strip()
            if not data_url:
                self._set_status("Paste a Data URL into the Decode tab first.")
                return True
            try:
                canvas = CanvasState.from_data_url(data_url)
                self._ensure_preview()
                self._preview.LoadCanvasFromState(canvas)
                self._orig_w = canvas.w
                self._orig_h = canvas.h
                self.SetInt32(EDT_WIDTH,  canvas.w, min=1, max=8192)
                self.SetInt32(EDT_HEIGHT, canvas.h, min=1, max=8192)
                self.SetString(TXT_ORIG_SIZE, "  Canvas: {}x{}".format(canvas.w, canvas.h))
                self.Enable(BTN_APPLY,    True)
                self.Enable(BTN_SAVE_PNG, True)
                self._set_status("Imported {}x{} px into editor.".format(canvas.w, canvas.h))
            except Exception as e:
                self._set_status("Import error: {}".format(e))

        elif id == BTN_APPLY:
            # Compute processed result and write it back into the draw canvas
            canvas = self._preview._ua._canvas if self._preview else None
            if not canvas:
                self._set_status("No canvas to apply to.")
                return True
            use_resize     = self.GetBool(CHK_RESIZE)
            use_hard_alias = self.GetBool(CHK_AA)
            target_w       = self.GetInt32(EDT_WIDTH)
            target_h       = self.GetInt32(EDT_HEIGHT)
            threshold      = int(self.GetInt32(EDT_THRESHOLD) / 100.0 * 255)
            if not use_resize and not use_hard_alias:
                self._set_status("Enable Resize or Hard Aliasing first.")
                return True
            # Push undo before modifying
            self._preview._ua.PushUndo()
            result = canvas
            if use_resize and (target_w != canvas.w or target_h != canvas.h):
                scaled = CanvasState(target_w, target_h)
                for dy in range(target_h):
                    for dx in range(target_w):
                        sx = int(dx * canvas.w / float(target_w))
                        sy = int(dy * canvas.h / float(target_h))
                        scaled.set(dx, dy, canvas.get(sx, sy))
                result = scaled
            if use_hard_alias:
                aliased = CanvasState(result.w, result.h)
                for y in range(result.h):
                    for x in range(result.w):
                        r, g, b, a = result.get(x, y)
                        new_a = 255 if a >= threshold else 0
                        if new_a == 0:
                            r, g, b = 0, 0, 0
                        aliased.set(x, y, (r, g, b, new_a))
                result = aliased
            # Write result back to draw canvas
            self._preview.LoadCanvasFromState(result)
            self._orig_w = result.w
            self._orig_h = result.h
            self.SetInt32(EDT_WIDTH,  result.w, min=1, max=8192)
            self.SetInt32(EDT_HEIGHT, result.h, min=1, max=8192)
            self.SetString(TXT_ORIG_SIZE, "  Canvas: {}x{}".format(result.w, result.h))
            self._set_status("Applied: {}x{} px.".format(result.w, result.h))

        elif id in (CHK_AA, CHK_RESIZE, EDT_THRESHOLD):
            if id == CHK_RESIZE:
                self._update_resize_enable()
            # Push canvas view if canvas exists, else push file preview
            canvas = self._preview._ua._canvas if self._preview else None
            if canvas:
                self._push_canvas_view()
            else:
                self._push_to_preview()

        elif id in (EDT_WIDTH, EDT_HEIGHT):
            self._update_proportional(id)
            canvas = self._preview._ua._canvas if self._preview else None
            if canvas:
                self._push_canvas_view()
            else:
                self._push_to_preview()

        elif id == BTN_SAVE_PNG:
            canvas = self._preview.GetOrigCanvas() if self._preview else None
            if not canvas:
                self._set_status("No canvas to save.")
                return True
            path = c4d.storage.SaveDialog(
                title="Save Canvas as PNG",
                force_suffix="png", def_path="", def_file="canvas.png"
            )
            if path:
                if not path.lower().endswith(".png"):
                    path += ".png"
                try:
                    raw = _write_png_rgba(canvas)
                    with open(path, "wb") as f:
                        f.write(raw)
                    self._set_status("Saved {}x{} px -> {}".format(
                        canvas.w, canvas.h, os.path.basename(path)))
                except Exception as e:
                    self._set_status("Save error: {}".format(e))

        elif id == BTN_ENCODE:
            # If editor has a canvas (draw OR view mode) - encode canvas
            has_canvas = self._preview and self._preview.GetOrigCanvas()
            if has_canvas:
                self._encode_canvas()
                return True
            if not self._path:
                self._set_status("Please select a file first.")
                return True
            if not os.path.isfile(self._path):
                self._set_status("File not found.")
                return True
            try:
                use_resize     = self.GetBool(CHK_RESIZE)
                use_hard_alias = self.GetBool(CHK_AA)
                use_chunks     = self.GetBool(CHK_CHUNKS)
                target_w       = self.GetInt32(EDT_WIDTH)
                target_h       = self.GetInt32(EDT_HEIGHT)
                threshold      = int(self.GetInt32(EDT_THRESHOLD) / 100.0 * 255)
                mime           = get_mime(self._path)
                if use_resize or use_hard_alias:
                    processed = process_bitmap(self._path, use_resize, target_w, target_h, use_hard_alias, threshold)
                    tmp_path  = get_temp_path("c4d_b64_processed_tmp.png")
                    processed.Save(tmp_path, c4d.FILTER_PNG)
                    with open(tmp_path, "rb") as f:
                        raw = f.read()
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    mime = "image/png"
                else:
                    with open(self._path, "rb") as f:
                        raw = f.read()
                b64      = base64.b64encode(raw).decode("ascii")
                data_url = "data:{};base64,{}".format(mime, b64)
                self._result = data_url
                notes = []
                if use_resize:
                    notes.append("{}x{} px".format(target_w, target_h))
                if use_hard_alias:
                    notes.append("hard alias")
                note_str = "  |  " + ", ".join(notes) if notes else ""
                kb = len(raw) / 1024.0
                self._set_status("OK  |  {:.1f} KB  |  {} chars  |  {}{}".format(
                    kb, len(b64), mime, note_str))
                display = format_base64_python(b64) if use_chunks else b64
                self.SetString(TXT_RESULT, display)
                # Feed strip with editor canvas if available, else None (shows hint)
                strip_canvas = self._preview.GetOrigCanvas() if self._preview else None
                self._strip_ua.SetCanvas(strip_canvas)
            except Exception as e:
                self._set_status("Error: {}".format(e))

        elif id == BTN_CLEAR:
            self._path   = ""
            self._result = ""
            self._orig_w = 0
            self._orig_h = 0
            self._set_status("")
            self.SetString(TXT_RESULT,    "")
            self.SetString(TXT_ORIG_SIZE, "")
            self.Enable(BTN_SAVE_PNG, False)
            self._strip_ua.SetCanvas(None)

        return super().Command(id, msg)

    def AskClose(self):
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
_main_dlg = Base64Dlg()

def main():
    _main_dlg.Open(
        dlgtype=c4d.DLG_TYPE_ASYNC,
        pluginid=1059995,
        xpos=-2, ypos=-2,
        defaultw=660, defaulth=440
    )

if __name__ == "__main__":
    main()
