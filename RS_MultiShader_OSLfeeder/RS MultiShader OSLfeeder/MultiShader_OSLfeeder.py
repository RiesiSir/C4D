# ============================================

# Script Name:   RS_MultiShader_OSLfeeder
# Description:   Batch imports images from selected folder and connects to a MultiTexture OSL.
#                It also generates by default a RSMG User Data (Interger) as Index input for direct use on cloner.
# Author:        RiesiSir | mail@andreasriesener.com
# Version:       0.2
# Date:          2026-04-27
# C4D Version:   2026.2
# RS Version:    2026.5
# ============================================


import c4d
import os
import re
import maxon

# ── Redshift IDs ──────────────────────────────────────────────────────────────
RS_NODESPACE        = "com.redshift3d.redshift4c4d.class.nodespace"
PORT_SOURCECODE     = "com.redshift3d.redshift4c4d.node.osl.internal.sourcecode"
PORT_SOURCEMODE     = "com.redshift3d.redshift4c4d.node.osl.internal.sourcemode"
ID_TEXTURESAMPLER   = "com.redshift3d.redshift4c4d.nodes.core.texturesampler"
PORT_TEX0           = "com.redshift3d.redshift4c4d.nodes.core.texturesampler.tex0"
PORT_TEX_OUTCOLOR   = "com.redshift3d.redshift4c4d.nodes.core.texturesampler.outcolor"
ID_INTEGER_USERDATA = "com.redshift3d.redshift4c4d.nodes.core.rsuserdatainteger"
PORT_USERDATA_OUT   = "com.redshift3d.redshift4c4d.nodes.core.rsuserdatainteger.out"


def natural_sort_key(s):
    return [int(c) if c.isdigit() else c.lower()
            for c in re.split(r'(\d+)', s)]


def build_osl(count):
    tex_inputs = '\n'.join(
        '    color Tex{i} = color(0,0,0) [[ string label = "Texture {i}", string page = "Textures" ]],'.format(i=i)
        for i in range(count)
    )
    if_block = '\n    '.join(
        '{kw} (textureIndex == {i}) OutColor = Tex{i};'.format(
            kw='if' if i == 0 else 'else if', i=i)
        for i in range(count)
    )
    return '''shader MultiTexture(
    int IndexInput = 0 [[
        string label = "Index Input",
        string page = "Settings"
    ]],
    int Mode = 0 [[
        string label = "Mode",
        string page = "Settings",
        string widget = "mapper",
        string options = "Sequential:0|Random:1"
    ]],
    int Seed = 0 [[
        string label = "Seed",
        string page = "Settings",
        int min = 0
    ]],
    int TextureCount = {count} [[
        string label = "Texture Count",
        string page = "Settings",
        int min = 1,
        int max = {count}
    ]],
    color FallbackColor = color(0.7, 0.7, 0.7) [[
        string label = "Fallback Color",
        string page = "Settings"
    ]],
{tex_inputs}
    output color OutColor = color(0,0,0),
    output float OutAlpha = 1.0,
    output int   OutIndex = 0
)
{{
    int textureIndex = 0;
    if (Mode == 0) {{
        textureIndex = IndexInput % TextureCount;
    }} else {{
        int h = (IndexInput + Seed) * 1664525 + 1013904223;
        h = h ^ (h >> 16);
        h = h * 22695477;
        h = h ^ (h >> 13);
        textureIndex = int(abs(h % TextureCount));
    }}
    textureIndex = clamp(textureIndex, 0, TextureCount - 1);
    OutIndex = textureIndex;
    OutColor = FallbackColor;
    {if_block}
}}'''.format(count=count, tex_inputs=tex_inputs, if_block=if_block)


def get_selected_osl_node():
    mat = doc.GetActiveMaterial()
    if mat is None:
        return None, None
    node_mat = mat.GetNodeMaterialReference()
    if node_mat is None:
        return None, None
    graph = node_mat.GetGraph(maxon.Id(RS_NODESPACE))
    if graph.IsNullValue():
        return None, None
    selected = []
    maxon.GraphModelHelper.GetSelectedNodes(graph, maxon.NODE_KIND.NODE, selected)
    for node in selected:
        try:
            asset_id = node.GetValue("net.maxon.node.attribute.assetid")[0]
            if "osl" in str(asset_id).lower():
                return node, graph
        except Exception:
            continue
    return None, None


def find_osl_input_port(osl_node, port_name_lower):
    for port in osl_node.GetInputs().GetChildren():
        if port_name_lower in str(port.GetId()).lower():
            return port
    return None


def main():
    # ── 1. Find selected OSL node ─────────────────────────────────────────────
    osl_node, graph = get_selected_osl_node()
    if osl_node is None:
        c4d.gui.MessageDialog(
            "No OSL node selected!\n\n"
            "Please select an OSL node\n"
            "in the Redshift Node Editor."
        )
        return

    # ── 2. Select texture folder ──────────────────────────────────────────────
    folder = c4d.storage.LoadDialog(
        c4d.FILESELECTTYPE_ANYTHING,
        "Select Texture Folder",
        c4d.FILESELECT_DIRECTORY
    )
    if not folder:
        return

    # ── 3. Read and sort texture files ────────────────────────────────────────
    EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr")
    files = sorted(
        [f for f in os.listdir(folder)
         if os.path.splitext(f)[1].lower() in EXTENSIONS],
        key=natural_sort_key
    )
    if not files:
        c4d.gui.MessageDialog("No textures found in:\n" + folder)
        return

    count = len(files)
    tex_nodes = []

    # ── 4. Transaction 1: OSL code + UserData + TextureSampler nodes ──────────
    with graph.BeginTransaction() as transaction:
        mode_port = osl_node.GetInputs().FindChild(PORT_SOURCEMODE)
        if not mode_port.IsNullValue():
            mode_port.SetPortValue(0)

        code_port = osl_node.GetInputs().FindChild(PORT_SOURCECODE)
        if code_port.IsNullValue():
            c4d.gui.MessageDialog("Could not find OSL source code port.")
            return
        code_port.SetPortValue(maxon.String(build_osl(count)))

        ud_node = graph.AddChild(
            maxon.Id(), maxon.Id(ID_INTEGER_USERDATA), maxon.DataDictionary()
        )
        attr_port = ud_node.GetInputs().FindChild(
            "com.redshift3d.redshift4c4d.nodes.core.rsuserdatainteger.attribute"
        )
        if not attr_port.IsNullValue():
            attr_port.SetPortValue(maxon.String("RSMGID"))

        for i, filename in enumerate(files):
            abs_path = os.path.abspath(os.path.join(folder, filename)).replace('\\', '/')
            tex_node = graph.AddChild(
                maxon.Id(), maxon.Id(ID_TEXTURESAMPLER), maxon.DataDictionary()
            )
            tex_node.SetValue(
                "net.maxon.node.base.name",
                maxon.String("Tex{:02d}_{}".format(i, os.path.splitext(filename)[0]))
            )
            path_port = tex_node.GetInputs().FindChild(PORT_TEX0).FindChild("path")
            if not path_port.IsNullValue():
                path_port.SetPortValue(maxon.Url("file:///" + abs_path))
            tex_nodes.append(tex_node)

        transaction.Commit()

    # ── 5. Force compile so OSL input ports become available ──────────────────
    doc.GetActiveMaterial().Update(True, True)
    c4d.EventAdd()

    # ── 6. Transaction 2: Connect all nodes ───────────────────────────────────
    with graph.BeginTransaction() as transaction:
        ud_out = ud_node.GetOutputs().FindChild(PORT_USERDATA_OUT)
        index_port = find_osl_input_port(osl_node, "indexinput")
        if not ud_out.IsNullValue() and index_port is not None:
            ud_out.Connect(index_port)
        else:
            print("WARNING: Could not connect UserData -> IndexInput")

        for i, tex_node in enumerate(tex_nodes):
            out_color = tex_node.GetOutputs().FindChild(PORT_TEX_OUTCOLOR)
            osl_tex_port = find_osl_input_port(osl_node, "tex{}".format(i))
            if out_color.IsNullValue():
                print("WARNING: outcolor port not found on tex node {}".format(i))
                continue
            if osl_tex_port is None:
                print("WARNING: OSL input port 'tex{}' not found".format(i))
                continue
            out_color.Connect(osl_tex_port)

        transaction.Commit()

    c4d.EventAdd()

    c4d.gui.MessageDialog(
        "Done!\n\n"
        "{} TextureSampler nodes created and connected.\n"
        "Folder: {}".format(count, folder)
    )


main()
