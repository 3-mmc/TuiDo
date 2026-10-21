"""Local syllabus previews. Text is escaped; Mermaid runs in strict mode."""

from html import escape
import json


def render_path_html(store, path_id):
    path = store.rows("SELECT * FROM paths WHERE id=?", (path_id,))[0]
    nodes, children, states = store.learning_snapshot(path_id)
    diagrams = []
    art = []
    if path["ascii_piece"]:
        art.append((path["title"], path["ascii_piece"]))
    graph = ["flowchart TD"]
    def label(text):
        return text.replace('"', "'").replace("\n", " ").replace("<", "").replace(">", "")
    for node in nodes.values():
        graph.append(f'  n{node["id"]}["{label(node["title"])}"]')
        if node["parent_id"] in nodes:
            graph.append(f'  n{node["parent_id"]} --> n{node["id"]}')
        by_uid = {n["uid"]: n["id"] for n in nodes.values()}
        for required in json.loads(node["requires"]):
            if required in by_uid:
                graph.append(f'  n{by_uid[required]} -. prerequisite .-> n{node["id"]}')
    if nodes:
        diagrams.append(("Learning map", "\n".join(graph)))
    if path["mermaid"]:
        diagrams.append((path["title"], path["mermaid"]))
    def outline(parent=None):
        result = "<ul>"
        for node_id in children.get(parent, []):
            node = nodes[node_id]
            result += f'<li><span class="state">{("□", "◧", "■")[states[node_id]]}</span> {escape(node["title"])}'
            if node["optional"]:
                result += " <small>optional</small>"
            if node["notes"]:
                result += f'<p>{escape(node["notes"])}</p>'
            if node["ascii_art"]:
                result += f'<pre>{escape(node["ascii_art"])}</pre>'
            if node["mermaid"]:
                diagrams.append((node["title"], node["mermaid"]))
            if node["ascii_piece"]:
                art.append((node["title"], node["ascii_piece"]))
            if node["resource_uid"]:
                resource = store.rows("SELECT title,url FROM resources WHERE uid=?", (node["resource_uid"],))[0]
                if resource["url"].startswith(("https://", "http://")):
                    result += f'<p><a href="{escape(resource["url"], quote=True)}" rel="noreferrer">{escape(resource["title"])}</a></p>'
            result += outline(node_id) + "</li>"
        return result + "</ul>"
    body = outline()
    diagrams_html = "".join(f'<section><h2>{escape(title)}</h2><pre class="mermaid">{escape(source)}</pre><details><summary>Diagram source</summary><pre>{escape(source)}</pre></details></section>' for title, source in diagrams)
    art_html = "".join(f'<section><h2>{escape(title)} · ASCII scene</h2><ascii-art piece="{escape(piece, quote=True)}" mono></ascii-art></section>' for title, piece in art)
    art_script = '<script type="module" src="https://www.ascii-magic.com/ascii/ascii.js"></script>' if art else ""
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + escape(path["title"]) + """ · TuiDo</title>
<style>
body{max-width:1000px;margin:40px auto;padding:0 24px;background:#101d2b;color:#dbe6ef;font:17px/1.65 system-ui}
h1,h2{color:#a6dace}section{margin:40px 0}li{margin:10px 0}p,small{color:#a7bdcf}
pre{white-space:pre-wrap;overflow:auto;background:#142437;padding:18px}a,.state{color:#9ae2c9}
.mermaid{background:#f3f7fa;color:#142437}svg{max-width:100%;height:auto}
ascii-art{display:block;min-height:200px;color:#9ae2c9}
</style><main><h1>""" + escape(path["title"]) + "</h1><p>" + escape(path["description"]) + "</p>" + ("<pre>" + escape(path["ascii_art"]) + "</pre>" if path["ascii_art"] else "") + body + diagrams_html + art_html + art_script + """
<p>Diagram rendering loads Mermaid 12.2.0 from jsDelivr. The syllabus and diagram source remain readable offline.</p>
<p>Optional animated scenes are provided by <a href="https://www.ascii-magic.com/ascii">ASCII Magic</a> and load from that site when selected in the syllabus.</p>
</main><script type="module">
try {
 const {default: mermaid} = await import('https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.esm.min.mjs');
 mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'default',flowchart:{htmlLabels:false},
   secure:['secure','securityLevel','startOnLoad','maxTextSize','htmlLabels'],maxTextSize:50000});
 await mermaid.run({querySelector:'.mermaid'});
} catch(error) { console.warn('Diagram source is available below each diagram.',error); }
</script></html>"""
