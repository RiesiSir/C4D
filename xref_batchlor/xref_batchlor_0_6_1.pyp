# ============================================
# Script Name:   Xref Batchlor
# Description:   auto batch setup for Cinema4D xref pipeline
# Author:        RiesiSir | mail@andreasriesener.com
# AI Assistant:  Claude
# Version:       0.6.1
# Date:          2026-10-28
# C4D Version:   2025+
# ============================================

import c4d
import os
import re
import base64
import struct
import zlib
import webbrowser
from c4d import gui, storage
import maxon

# --- Plugin ---
PLUGIN_ID   = 1067543
PLUGIN_NAME = "XRef Batchlor"
PLUGIN_HELP = "Auto batch setup for Cinema 4D xref pipeline"

# --- UI IDs ---
ID_EXECUTE        = 1000
ID_PATH           = 1001
ID_PREFIX         = 1002
ID_SUFFIX         = 1003
ID_USE_ID         = 1004
ID_DEL_ORIG       = 1005
ID_ANIM           = 1006
ID_BROWSE         = 1007
ID_SKIP_EXISTING  = 1009
ID_TRANSFER_MATS  = 1010
ID_CLEAN_KEYS     = 1011
ID_WARN_ANIM      = 1020
ID_WARN_MATS      = 1021
ID_WARN_GLOBAL    = 1022
ID_PREVIEW        = 1023
ID_REFRESH        = 1025
ID_OPEN_FOLDER    = 1024
ID_RESET_BIND     = 1026
ID_RESET_MORPHS   = 1027
ID_CLEANUP_GROUP  = 1028
ID_SIG_AREA       = 10099

FILE_DESC_ID = c4d.DescID(c4d.DescLevel(c4d.ID_CA_XREF_FILE, c4d.DTYPE_FILENAME, 0))

WARN_GENERATOR = "⚠ Needs Generator OFF to work"
WARN_NAMESPACE = "⚠ Set Namespace to None"
WARN_GLOBAL    = "XRef Setting State |"


DEFAULT_FOLDER = "xrefs"

def resolve_folder(doc, raw):
    """Resolve empty, relative or absolute input to an absolute path."""
    folder = (raw or "").strip().strip('"').strip("'") or DEFAULT_FOLDER
    folder = os.path.expanduser(folder)
    if not os.path.isabs(folder):
        folder = os.path.join(doc.GetDocumentPath() or "", folder)
    return os.path.normpath(folder)


def get_next_id(target_dir):
    max_id = 0
    if not os.path.exists(target_dir): return 1
    regex = re.compile(r'^(\d+)_')
    try:
        for f in os.listdir(target_dir):
            m = regex.match(f)
            if m:
                n = int(m.group(1))
                if n > max_id: max_id = n
    except: pass
    return max_id + 1

def find_existing_file(target_dir, name, suffix, prefix):
    """
    Find existing XRef file with exact {prefix}{name}{suffix}.c4d match.

    Strips optional 3-digit ID prefix (001_, 002_, etc.) then does exact match.

    Examples (prefix="HOUSE_", name="Table", suffix="_xref"):
    - "001_HOUSE_Table_xref.c4d" → strip ID → "HOUSE_Table_xref.c4d" → Match ✓
    - "HOUSE_Table_xref.c4d" → no ID → "HOUSE_Table_xref.c4d" → Match ✓
    - "001_CITY_Table_xref.c4d" → strip ID → "CITY_Table_xref.c4d" → No match ✗

    This prevents HOUSE_Table from overwriting CITY_Table.
    """
    if not os.path.exists(target_dir): return None
    expected = f"{prefix}{name}{suffix}.c4d"
    id_pattern = re.compile(r'^(\d{3})_')

    for filename in os.listdir(target_dir):
        stripped = id_pattern.sub('', filename, count=1)
        if stripped == expected:
            return os.path.join(target_dir, filename)
    return None


def preview_changes(doc, sel, target_dir, prefix, suffix, use_id, skip_existing):
    """
    Analyze what will happen to each selected object without actually doing it.
    Returns list of dicts: [{name, existing_file, action, target_file}, ...]
    """
    if not os.path.exists(target_dir):
        return []

    roots = [o for o in sel if o.GetUp() not in sel]
    current_id = get_next_id(target_dir) if use_id else 1
    results = []

    for original in roots:
        name = original.GetName()
        existing_path = find_existing_file(target_dir, name, suffix, prefix)

        if existing_path and skip_existing:
            action = "Skip (Relink)"
            target = os.path.basename(existing_path)
        elif existing_path:
            action = "Overwrite"
            target = os.path.basename(existing_path)
        else:
            action = "Create New"
            id_str = f"{str(current_id).zfill(3)}_" if use_id else ""
            target = f"{id_str}{prefix}{name}{suffix}.c4d"
            if use_id: current_id += 1

        results.append({
            'name': name,
            'existing': os.path.basename(existing_path) if existing_path else "-",
            'action': action,
            'target': target
        })

    return results
def read_xref_settings(doc):
    """
    Write a minimal dummy .c4d, load it into a temp XRef to force SceneHook
    population, then read settings via BaseContainer. Namespace detection:
      BC id=1007 == ''         → None
      BC id=1007 == dummy_stem → Ref Name
      anything else            → Custom
    """
    import tempfile
    doc_path = doc.GetDocumentPath()
    base_dir = doc_path if doc_path else tempfile.gettempdir()
    dummy_path = os.path.join(base_dir, "__xref_settings_probe__.c4d")
    dummy_stem = "__xref_settings_probe__"

    dummy_doc = c4d.documents.BaseDocument()
    null = c4d.BaseObject(c4d.Onull)
    null.SetName("__probe__")
    dummy_doc.InsertObject(null)
    c4d.documents.SaveDocument(dummy_doc, dummy_path,
        c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST, c4d.FORMAT_C4DEXPORT)

    tmp = c4d.BaseObject(c4d.Oxref)
    doc.InsertObject(tmp)
    tmp.SetParameter(FILE_DESC_ID, dummy_path, c4d.DESCFLAGS_SET_USERINTERACTION)
    doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_NONE)

    gen      = tmp[c4d.ID_CA_XREF_GENERATOR]
    relative = tmp[c4d.ID_CA_XREF_RELATIVE]

    bc = tmp.GetDataInstance()
    ns_raw = bc.GetString(1007) if bc else ""
    if ns_raw == "":
        ns_mode = "None"
    elif ns_raw == dummy_stem:
        ns_mode = "Ref Name"
    else:
        ns_mode = "Custom"

    tmp.SetParameter(FILE_DESC_ID, "", c4d.DESCFLAGS_SET_USERINTERACTION)
    doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_NONE)
    tmp.Remove()
    try: os.remove(dummy_path)
    except: pass
    c4d.EventAdd()

    return gen, ns_mode, relative

# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------

def is_psr_track(track):
    if len(track.GetDescriptionID()) < 1: return False
    psr_ids = [c4d.ID_BASEOBJECT_POSITION, c4d.ID_BASEOBJECT_ROTATION, c4d.ID_BASEOBJECT_SCALE,
               c4d.ID_BASEOBJECT_REL_POSITION, c4d.ID_BASEOBJECT_REL_ROTATION, c4d.ID_BASEOBJECT_REL_SCALE]
    return track.GetDescriptionID()[0].id in psr_ids

def transfer_tracks(source, target, psr_only=False, skip_psr=False):
    if not source or not target: return
    for track in source.GetCTracks():
        psr = is_psr_track(track)
        if psr_only and not psr: continue
        if skip_psr and psr: continue
        target.InsertTrackSorted(track.GetClone(c4d.COPYFLAGS_0))
    if isinstance(source, c4d.BaseObject) and isinstance(target, c4d.BaseObject):
        s_tags, t_tags = source.GetTags(), target.GetTags()
        for i in range(min(len(s_tags), len(t_tags))):
            for t_track in s_tags[i].GetCTracks():
                t_tags[i].InsertTrackSorted(t_track.GetClone(c4d.COPYFLAGS_0))

def sync_hierarchy(source, target, transfer_mats, is_root=False):
    if not source or not target: return
    target.SetEditorMode(source.GetEditorMode())
    target.SetRenderMode(source.GetRenderMode())
    if is_root:
        target.SetMl(c4d.Matrix())
        transfer_tracks(source, target, skip_psr=True)
    else:
        target.SetMl(source.GetMl())
        transfer_tracks(source, target)
    if transfer_mats:
        s_tags, t_tags = source.GetTags(), target.GetTags()
        for tt in t_tags:
            if tt.GetType() == c4d.Ttexture: tt.Remove()
        for st in reversed(s_tags):
            if st.GetType() == c4d.Ttexture:
                clone = st.GetClone(c4d.COPYFLAGS_0)
                target.InsertTag(clone)
                transfer_tracks(st, clone)
    sc, tc = source.GetDown(), target.GetDown()
    while sc:
        if tc:
            sync_hierarchy(sc, tc, transfer_mats, is_root=False)
            tc = tc.GetNext()
        sc = sc.GetNext()

def get_noxref_layer(doc):
    root = doc.GetLayerObjectRoot()
    curr = root.GetDown()
    while curr:
        if curr.GetName() == "NoXref": return curr
        curr = curr.GetNext()
    layer = c4d.BaseList2D(c4d.Olayer)
    layer.SetName("NoXref")
    layer[c4d.ID_LAYER_COLOR] = c4d.Vector(1, 0, 0)
    layer[c4d.ID_LAYER_XREF] = False
    layer.InsertUnderLast(root)
    return layer

def reset_bind_poses(obj):
    """Reset bind pose on all weight tags recursively"""
    def process_obj(o):
        for tag in o.GetTags():
            if tag.GetType() == c4d.Tweights:
                c4d.CallButton(tag, c4d.ID_CA_WEIGHT_TAG_RESET_BUTTON)
        child = o.GetDown()
        while child:
            process_obj(child)
            child = child.GetNext()
    process_obj(obj)

def reset_posemorphs(obj):
    """Reset all PoseMorph strengths to 0 recursively"""
    def process_obj(o):
        for tag in o.GetTags():
            if tag.GetType() == c4d.Tposemorph:
                for i in range(1, tag.GetMorphCount()):  # Skip index 0 = Base morph
                    desc_id = tag.GetMorphID(i)
                    tag[desc_id] = 0.0
        child = o.GetDown()
        while child:
            process_obj(child)
            child = child.GetNext()
    process_obj(obj)

def build_ref_doc(doc, original, transfer_mats, clean_keys, reset_bind, reset_morphs):
    temp_doc, aliastrans = c4d.documents.BaseDocument(), c4d.AliasTrans()
    if not aliastrans.Init(doc): return None
    layer = get_noxref_layer(temp_doc) if transfer_mats else None

    def process_mats_recursive(obj):
        for tag in obj.GetTags():
            if tag.GetType() == c4d.Ttexture:
                m = tag[c4d.TEXTURETAG_MATERIAL]
                if m and not temp_doc.SearchMaterial(m.GetName()):
                    m_clone = m.GetClone(c4d.COPYFLAGS_0, aliastrans)
                    if transfer_mats and layer:
                        m_clone[c4d.ID_LAYER_LINK] = layer
                    temp_doc.InsertMaterial(m_clone)
        c = obj.GetDown()
        while c: process_mats_recursive(c); c = c.GetNext()

    process_mats_recursive(original)
    clone = original.GetClone(c4d.COPYFLAGS_0, aliastrans)
    aliastrans.Translate(True)

    # Apply resets BEFORE track cleanup (only if cleanup is enabled)
    if clean_keys:
        if reset_bind:
            reset_bind_poses(clone)
        if reset_morphs:
            reset_posemorphs(clone)

    def clean_obj(obj, is_root=False):
        # Handle tracks
        if clean_keys:
            # Cleanup ON: Delete all tracks (root + children)
            for t in obj.GetCTracks():
                t.Remove()
        elif is_root:
            # Cleanup OFF: Only deactivate root tracks (don't delete)
            for t in obj.GetCTracks():
                if is_psr_track(t):
                    t[c4d.ID_CTRACK_ANIMOFF] = True
        
        # Handle tags
        for tag in obj.GetTags():
            if transfer_mats and layer and tag.GetType() == c4d.Ttexture:
                tag[c4d.ID_LAYER_LINK] = layer
            if clean_keys:
                for tt in tag.GetCTracks():
                    tt.Remove()
        
        c = obj.GetDown()
        while c: clean_obj(c); c = c.GetNext()

    clean_obj(clone, is_root=True)
    clone.SetMl(c4d.Matrix())
    temp_doc.InsertObject(clone)
    return temp_doc


def process_objects(doc, sel, target_dir, prefix, suffix, use_id, transfer_anim,
                    del_orig, skip_existing, transfer_mats, clean_keys, reset_bind, reset_morphs):
    stat_skipped, stat_overwritten, stat_new = 0, 0, 0
    roots = [o for o in sel if o.GetUp() not in sel]
    total_objs = len(roots)
    current_id = get_next_id(target_dir) if use_id else 1

    doc.StartUndo()
    for i, original in enumerate(roots):
        name = original.GetName()
        c4d.gui.StatusSetText(f"Processing {i + 1}/{total_objs} : {name}")

        existing_path = find_existing_file(target_dir, name, suffix, prefix)

        if existing_path and skip_existing:
            final_file_path = existing_path
            stat_skipped += 1
        elif existing_path:
            final_file_path = existing_path
            stat_overwritten += 1
            ref_doc = build_ref_doc(doc, original, transfer_mats, clean_keys, reset_bind, reset_morphs)
            c4d.documents.SaveDocument(ref_doc, final_file_path,
                c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST, c4d.FORMAT_C4DEXPORT)
        else:
            id_str = f"{str(current_id).zfill(3)}_" if use_id else ""
            filename = f"{id_str}{prefix}{name}{suffix}.c4d"
            final_file_path = os.path.join(target_dir, filename)
            stat_new += 1
            if use_id: current_id += 1
            ref_doc = build_ref_doc(doc, original, transfer_mats, clean_keys, reset_bind, reset_morphs)
            c4d.documents.SaveDocument(ref_doc, final_file_path,
                c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST, c4d.FORMAT_C4DEXPORT)

        xref = c4d.BaseObject(c4d.Oxref)
        xref.SetName(os.path.splitext(os.path.basename(final_file_path))[0])
        doc.InsertObject(xref, parent=original.GetUp(), pred=original)
        xref.SetMl(original.GetMl())
        xref.SetParameter(FILE_DESC_ID, final_file_path, c4d.DESCFLAGS_SET_USERINTERACTION)
        doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_NONE)

        transfer_tracks(original, xref, psr_only=True)
        if transfer_anim:
            root_in_xref = xref.GetDown()
            if root_in_xref:
                sync_hierarchy(original, root_in_xref, transfer_mats, is_root=True)

        if del_orig:
            doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, original)
            original.Remove()
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, xref)

        # Update progress bar after completing this object
        c4d.gui.StatusSetBar(int((float(i + 1) / total_objs) * 100))

    doc.EndUndo()

    # Show final statistics in C4D status bar
    c4d.gui.StatusSetText(f"XRef Batchlor: {total_objs} Processed | {stat_new} New | "
                          f"{stat_overwritten} Overwritten | {stat_skipped} Linked from existing")
    c4d.gui.StatusSetBar(100)

    c4d.CallCommand(12147)
    doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_NONE)
    c4d.EventAdd(c4d.EVENT_FORCEREDRAW)

# ---------------------------------------------------------------------------
# UI Dialog
# ---------------------------------------------------------------------------

class PreviewDialog(gui.GeDialog):
    def __init__(self, preview_data, folder_path):
        super().__init__()
        self.preview_data, self.folder_path, self._bar_colors = preview_data, folder_path, {}

    def CreateLayout(self):
        self.SetTitle("Preview Changes")
        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, cols=1, rows=0)
        self.GroupBorderSpace(10, 10, 10, 10)

        # Header with button
        self.GroupBegin(0, c4d.BFH_SCALEFIT, cols=2)
        self.AddStaticText(0, c4d.BFH_SCALEFIT, name=f"{len(self.preview_data)} object(s) will be processed:")
        self.AddButton(ID_OPEN_FOLDER, c4d.BFH_RIGHT, name="Open Folder")
        self.GroupEnd()
        self.AddStaticText(0, c4d.BFH_LEFT, name="ℹ If naming doesn't match expectations, rename your objects before processing.")
        self.AddSeparatorH(0)

        # Table header
        self.GroupBegin(0, c4d.BFH_SCALEFIT, cols=5)
        self.GroupBorderSpace(5, 3, 5, 3)
        headers = [("", 4), ("Object Name", 136), ("Existing File", 180), ("Action", 110), ("Target File", 180)]
        for txt, w in headers:
            self.AddStaticText(0, c4d.BFH_SCALEFIT if w == 180 and txt == "Target File" else c4d.BFH_LEFT, w, 0, txt)
        self.GroupEnd()
        self.AddSeparatorH(0)

        # Scrollable content
        self.ScrollGroupBegin(9000, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, c4d.SCROLLGROUP_VERT | c4d.SCROLLGROUP_AUTOVERT, 0, 0)
        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_TOP, cols=1)
        self.GroupSpace(0, 1)

        # Colors
        cols = {'Create': c4d.Vector(1.0, 0.5, 0.0), 'Overwrite': c4d.Vector(0.85, 0.2, 0.2), 'Skip': c4d.Vector(0.4, 0.85, 0.7)}

        for i, item in enumerate(self.preview_data):
            self.GroupBegin(20000+i, c4d.BFH_SCALEFIT, cols=5)
            self.GroupBorderSpace(5, 2, 5, 2)

            # Color bar
            bar = 25000+i
            self.AddColorField(bar, c4d.BFH_LEFT, 6, 18, colorflags=c4d.DR_COLORFIELD_NO_SCREENPICKER)
            self._bar_colors[bar] = cols.get(item['action'].split()[0], cols['Skip'])

            # Cells
            cells = [(item['name'], 136), (item['existing'], 180), (item['action'], 110), (item['target'], 180)]
            for j, (val, w) in enumerate(cells):
                self.AddStaticText(30000+i*4+j, c4d.BFH_SCALEFIT if j==3 else c4d.BFH_LEFT, w, 0, val)
            self.GroupEnd()

        self.GroupEnd()
        self.GroupEnd()
        self.AddSeparatorH(0)

        # Summary
        cnts = [sum(1 for x in self.preview_data if x['action']==a) for a in ['Create New','Overwrite','Skip (Relink)']]
        self.AddStaticText(0, c4d.BFH_CENTER, name=f"Summary: {cnts[0]} new, {cnts[1]} overwrite, {cnts[2]} skip")
        self.GroupEnd()
        return True

    def InitValues(self):
        for bar_id, color in self._bar_colors.items(): self.SetColorField(bar_id, color, 1.0, 1.0, 0)
        return True

    def Command(self, id, msg):
        if id == ID_OPEN_FOLDER and os.path.exists(self.folder_path): c4d.storage.ShowInFinder(self.folder_path, True)
        return True

# ---------------------------------------------------------------------------
# Signature Footer
# ---------------------------------------------------------------------------
_SIG_ICON_FULL_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAMCAYAAABr5z2BAAAAQklEQVR42mNgIBPU19f/B2EGuhoA"
    "00S2zWQZgE0TSQaRZQAhTbQxgJCmHiMjMAaxNcNqwJg6BhATQLicT7IB2MIJAG74zvGu0+RJAAAA"
    "AElFTkSuQmCC"
)


def _load_sig_icon():
    """Decode the signature icon (8-bit RGBA PNG) -> (pixels, w, h) or None."""
    try:
        raw = base64.b64decode(_SIG_ICON_FULL_B64)
        pos, idat, w, h = 8, [], 0, 0
        while pos < len(raw):
            length = struct.unpack(">I", raw[pos:pos+4])[0]
            ctype  = raw[pos+4:pos+8]
            cdata  = raw[pos+8:pos+8+length]
            pos   += 12 + length
            if ctype == b"IHDR":
                w, h = struct.unpack(">II", cdata[:8])
            elif ctype == b"IDAT":
                idat.append(cdata)
            elif ctype == b"IEND":
                break
        data = zlib.decompress(b"".join(idat))
        stride = 1 + w * 4
        px = []
        for y in range(h):
            base = y * stride + 1
            for x in range(w):
                o = base + x * 4
                px.append((data[o], data[o+1], data[o+2], data[o+3]))
        return px, w, h
    except Exception:
        return None


class SignatureArea(c4d.gui.GeUserArea):

    URL     = "https://andreasriesener.com/"
    MAIL    = "mail@andreasriesener.com"
    T_LEFT  = "created by RiesiSir"
    T_RIGHT = "mail@andreasriesener.com"
    ICON_H  = 16   # target icon height in px

    def __init__(self):
        self._sep_x = 0
        self._icon  = _load_sig_icon()

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

        # Icon centred between both texts; also splits the click zones
        mid_x = (left_x + w_left + right_x) // 2
        self._sep_x = mid_x

        if self._icon is not None:
            px, iw, ih = self._icon
            dst_h  = self.ICON_H
            dst_w  = max(1, int(iw * dst_h / float(ih)))
            icon_x = mid_x - dst_w // 2
            icon_y = y1 + (y2 - y1 - dst_h) // 2
            for dy in range(dst_h):
                for dx in range(dst_w):
                    r, g, b, a = px[int(dy * ih / float(dst_h)) * iw + int(dx * iw / float(dst_w))]
                    t = a / 255.0
                    self.DrawSetPen(c4d.Vector(
                        int(t*r + (1-t)*bg_r) / 255.0,
                        int(t*g + (1-t)*bg_g) / 255.0,
                        int(t*b + (1-t)*bg_b) / 255.0))
                    self.DrawRectangle(icon_x + dx, icon_y + dy, icon_x + dx, icon_y + dy)

    def InputEvent(self, msg):
        if msg[c4d.BFM_INPUT_DEVICE] == c4d.BFM_INPUT_MOUSE:
            if msg[c4d.BFM_INPUT_CHANNEL] == c4d.BFM_INPUT_MOUSELEFT:
                if msg[c4d.BFM_INPUT_X] < self._sep_x:
                    webbrowser.open(self.URL)
                else:
                    webbrowser.open("mailto:{}".format(self.MAIL))
        return True


class XRefBatchlorDialog(gui.GeDialog):

    def __init__(self):
        super().__init__()
        self._sig_area = SignatureArea()

    def CreateLayout(self):
        self.SetTitle("XRef Batchlor 0.6.1")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, cols=1)
        self.GroupBorderSpace(10, 10, 10, 10)
        self.GroupSpace(4, 3)

        # Folder
        self.AddStaticText(0, c4d.BFH_LEFT, name="XRef Target Folder:")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, cols=2)
        self.AddEditText(ID_PATH, c4d.BFH_SCALEFIT, 280, 0)
        self.AddButton(ID_BROWSE, c4d.BFH_RIGHT, name="Browse...")
        self.GroupEnd()

        # Naming
        self.GroupBegin(0, c4d.BFH_SCALEFIT, cols=4)
        self.AddStaticText(0, c4d.BFH_LEFT, name="Prefix")
        self.AddEditText(ID_PREFIX, c4d.BFH_SCALEFIT, 60, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, name="Suffix")
        self.AddEditText(ID_SUFFIX, c4d.BFH_SCALEFIT, 60, 0)
        self.GroupEnd()
        self.AddCheckbox(ID_USE_ID,        c4d.BFH_LEFT, 0, 0, "ID")
        self.AddCheckbox(ID_SKIP_EXISTING, c4d.BFH_LEFT, 0, 0, "Skip Existing & Relink")

        self.AddSeparatorH(0)

        # Options: 2-col grid (checkbox | inline warning)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, cols=2)
        self.AddCheckbox(ID_ANIM,          c4d.BFH_LEFT,     0, 0, "Transfer Animations")
        self.AddStaticText(ID_WARN_ANIM,   c4d.BFH_SCALEFIT, 0, 0, WARN_GENERATOR)
        self.AddCheckbox(ID_TRANSFER_MATS, c4d.BFH_LEFT,     0, 0, "Transfer Material Tags")
        self.AddStaticText(ID_WARN_MATS,   c4d.BFH_SCALEFIT, 0, 0, WARN_GENERATOR)
        self.GroupEnd()

        self.AddSeparatorH(0)

        # Cleanup Options - Border Group
        self.GroupBegin(ID_CLEANUP_GROUP, c4d.BFH_SCALEFIT, cols=3, title="Cleanup Options")
        self.GroupBorder(c4d.BORDER_GROUP_IN)
        self.GroupBorderSpace(5, 5, 5, 5)
        
        # Left column
        self.AddCheckbox(ID_CLEAN_KEYS, c4d.BFH_LEFT, 0, 0, "Cleanup Keys inside XRef File")
        self.AddStaticText(0, c4d.BFH_LEFT, 40, 0, "")  # Spacer
        # Right column
        self.AddCheckbox(ID_RESET_BIND, c4d.BFH_LEFT, 0, 0, "Reset Bind Poses")
        
        # Left column row 2
        self.AddCheckbox(ID_DEL_ORIG, c4d.BFH_LEFT, 0, 0, "Delete Original Objects")
        self.AddStaticText(0, c4d.BFH_LEFT, 40, 0, "")  # Spacer
        # Right column row 2
        self.AddCheckbox(ID_RESET_MORPHS, c4d.BFH_LEFT, 0, 0, "Reset PoseMorphs")
        
        self.GroupEnd()  # End Cleanup Options group

        self.AddSeparatorH(0)

        # Status line with refresh button (left side)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, cols=2)
        self.AddButton(ID_REFRESH, c4d.BFH_LEFT, 14, 0, "ℹ")
        self.AddStaticText(ID_WARN_GLOBAL, c4d.BFH_SCALEFIT, 0, 0, WARN_GLOBAL)
        self.GroupEnd()

        # Action buttons side by side
        self.GroupBegin(0, c4d.BFH_SCALEFIT, cols=2)
        self.AddButton(ID_PREVIEW, c4d.BFH_SCALEFIT, 0, 24, "Preview Changes")
        self.AddButton(ID_EXECUTE, c4d.BFH_SCALEFIT, 0, 24, "Process Selection")
        self.GroupEnd()
        self.GroupEnd()

        # Signature footer
        self.AddSeparatorH(0, c4d.BFH_SCALEFIT)
        if self.AddUserArea(ID_SIG_AREA, c4d.BFH_SCALEFIT, 0, 20):
            self.AttachUserArea(self._sig_area, ID_SIG_AREA)

        return True

    def InitValues(self):
        # Set defaults here, not in CreateLayout (gadgets must exist first)
        self.SetString(ID_PATH,   DEFAULT_FOLDER)
        self.SetString(ID_SUFFIX, "_xref")
        self.SetBool(ID_USE_ID,        True)
        self.SetBool(ID_ANIM,          True)
        self.SetBool(ID_TRANSFER_MATS, True)

        # Cleanup Options defaults (all OFF)
        self.SetBool(ID_CLEAN_KEYS,    False)
        self.SetBool(ID_DEL_ORIG,      False)
        self.SetBool(ID_RESET_BIND,    False)
        self.SetBool(ID_RESET_MORPHS,  False)
        self._update_warnings()
        self._update_cleanup_enable()
        return True

    def _update_warnings(self):
        doc = c4d.documents.GetActiveDocument()
        gen, ns_mode, relative = read_xref_settings(doc)

        warn_gen      = bool(gen)
        warn_ns       = ns_mode != "None"
        transfer_anim = self.GetBool(ID_ANIM)
        transfer_mats = self.GetBool(ID_TRANSFER_MATS)

        # Inline warnings — only visible when the option is active AND setting is wrong
        self.SetString(ID_WARN_ANIM,
            WARN_GENERATOR if (transfer_anim and warn_gen) else " ")

        mats_parts = []
        if transfer_mats and warn_gen: mats_parts.append(WARN_GENERATOR)
        if transfer_mats and warn_ns:  mats_parts.append(WARN_NAMESPACE)
        self.SetString(ID_WARN_MATS, "  ".join(mats_parts) if mats_parts else " ")

        # Global status line — always shows current state
        g = "ON" if gen else "OFF"
        p = "Relative" if relative else "Absolute"
        self.SetString(ID_WARN_GLOBAL,
            f"{WARN_GLOBAL} Generator: {g} | Name Space: {ns_mode} | Path: {p}")

    def _update_cleanup_enable(self):
        """Enable/disable Reset options based on Cleanup Keys checkbox"""
        cleanup_enabled = self.GetBool(ID_CLEAN_KEYS)
        self.Enable(ID_RESET_BIND, cleanup_enabled)
        self.Enable(ID_RESET_MORPHS, cleanup_enabled)

    def Command(self, id, msg):
        if id == ID_BROWSE:
            path = storage.LoadDialog(flags=c4d.FILESELECT_DIRECTORY,
                                      title="Select XRef Target Folder")
            if path: self.SetString(ID_PATH, path)


        elif id == ID_REFRESH:
            self._update_warnings()

        elif id == ID_CLEAN_KEYS:
            self._update_cleanup_enable()

        elif id == ID_PREVIEW:
            doc = c4d.documents.GetActiveDocument()
            folder = self.GetString(ID_PATH).strip() or DEFAULT_FOLDER

            # Validation
            if not doc.GetDocumentPath() and not os.path.isabs(folder):
                gui.MessageDialog("Please save your document first to use relative paths.")
                return True

            sel = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_0)
            if not sel:
                gui.MessageDialog("No objects selected.")
                return True

            abs_folder = resolve_folder(doc, folder)

            # Generate preview
            preview_data = preview_changes(
                doc, sel, abs_folder,
                self.GetString(ID_PREFIX), self.GetString(ID_SUFFIX),
                self.GetBool(ID_USE_ID), self.GetBool(ID_SKIP_EXISTING))

            if not os.path.isdir(abs_folder):
                gui.MessageDialog(f"Folder doesn't exist yet:\n{abs_folder}")
                return True
            if not preview_data:
                gui.MessageDialog("No objects to process.")
                return True

            # Show preview dialog
            preview_dlg = PreviewDialog(preview_data, abs_folder)
            preview_dlg.Open(c4d.DLG_TYPE_MODAL_RESIZEABLE, defaultw=650, defaulth=400)

        elif id == ID_EXECUTE:
            doc    = c4d.documents.GetActiveDocument()
            folder = self.GetString(ID_PATH).strip() or DEFAULT_FOLDER
            if not doc.GetDocumentPath() and not os.path.isabs(folder):
                gui.MessageDialog("Please save your document first.")
                return True
            abs_folder = resolve_folder(doc, folder)
            if not os.path.exists(abs_folder): os.makedirs(abs_folder)
            process_objects(
                doc, doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_0), abs_folder,
                self.GetString(ID_PREFIX), self.GetString(ID_SUFFIX),
                self.GetBool(ID_USE_ID),    self.GetBool(ID_ANIM),
                self.GetBool(ID_DEL_ORIG),  self.GetBool(ID_SKIP_EXISTING),
                self.GetBool(ID_TRANSFER_MATS), self.GetBool(ID_CLEAN_KEYS),
                self.GetBool(ID_RESET_BIND), self.GetBool(ID_RESET_MORPHS))
        return True

class XRefBatchlorCommand(c4d.plugins.CommandData):

    def __init__(self):
        self.dlg = None

    def _get_dlg(self):
        if self.dlg is None:
            self.dlg = XRefBatchlorDialog()
        return self.dlg

    def Execute(self, doc):
        return self._get_dlg().Open(c4d.DLG_TYPE_ASYNC, pluginid=PLUGIN_ID,
                                    defaultw=480, defaulth=0)

    def RestoreLayout(self, sec_ref):
        # Restore dialog after C4D layout reload
        return self._get_dlg().Restore(pluginid=PLUGIN_ID, secret=sec_ref)

    def GetState(self, doc):
        return c4d.CMD_ENABLED


if __name__ == '__main__':
    c4d.plugins.RegisterCommandPlugin(
        id=PLUGIN_ID,
        str=PLUGIN_NAME,
        info=0,
        icon=None,
        help=PLUGIN_HELP,
        dat=XRefBatchlorCommand())
