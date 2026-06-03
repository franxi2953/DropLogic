import os
import ast
import json
import math

def get_module_name(filepath, base_dir):
    rel = os.path.relpath(filepath, base_dir)
    return rel.replace('.py', '').replace('/', '.')

def parse_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    num_lines = len(content.splitlines())
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return num_lines, [], [], []

    public_funcs = []
    private_funcs = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            name = node.name
            if name.startswith('_') and name != '__init__':
                private_funcs.append(name)
            else:
                public_funcs.append(name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
            else:
                imports.append("." * node.level)
                
    return num_lines, public_funcs, private_funcs, imports

def generate():
    docs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    base_dir = os.path.abspath(os.path.join(docs_dir, '..'))
    package_dir = os.path.join(base_dir, 'droplogic')

    nodes = []
    edges = []
    
    modules = {}
    id_counter = 1

    folder_colors = [
        '#FFFFFF', '#F4F4F4', '#ECECEC', '#E4E4E4',
        '#DCDCDC', '#D4D4D4', '#CCCCCC'
    ]
    folder_level_info = {}
    folders_info = {}

    for root, dirs, files in os.walk(package_dir):
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
            
        rel_root = os.path.relpath(root, base_dir)
        folder_name = os.path.basename(root)
        dir_id = f"dir_{rel_root.replace('/', '_')}"
        
        rel_to_pkg = os.path.relpath(root, package_dir)
        level = 0 if rel_to_pkg == '.' else len(rel_to_pkg.split(os.sep))
        folder_level_info[dir_id] = level
        
        node_color = folder_colors[level % len(folder_colors)]
        
        parent_root = os.path.dirname(root)
        parent_id = f"dir_{os.path.relpath(parent_root, base_dir).replace('/', '_')}" if root != package_dir else None
        
        folders_info[dir_id] = {
            'name': folder_name,
            'rel_path': rel_to_pkg,
            'color': node_color,
            'parent_id': parent_id,
            'children': []
        }
        if parent_id and parent_id in folders_info:
            folders_info[parent_id]['children'].append(dir_id)

        is_root = level == 0
        f_size = 24 if is_root else 16
        f_margin = 18 if is_root else 12
        
        node_data = {
            'id': dir_id,
            'label': folder_name,
            'shape': 'box',
            'isFolder': True,
            'level': level,
            'borderWidth': 1,
            'color': {
                'background': node_color,
                'border': '#111111',
                'highlight': {'background': '#111111', 'border': '#111111'},
                'hover': {'background': '#111111', 'border': '#111111'}
            },
            'font': {'color': '#111111', 'face': 'Playfair Display, Georgia, Times New Roman, serif', 'size': f_size, 'bold': True},
            'margin': f_margin
        }
        
        if is_root:
            node_data['x'] = 0
            node_data['y'] = 0
            node_data['fixed'] = True
            
        nodes.append(node_data)

        if root != package_dir:
            edges.append({
                'id': f"edge_struct_{parent_id}_{dir_id}",
                'from': parent_id,
                'to': dir_id,
                'edgeType': 'struct',
                'color': {'color': '#111111'},
                'dashes': False,
                'arrows': '',
                'smooth': False,
                'length': 100 
            })

        for file in files:
            if file.endswith('.py') and not file.startswith('.'):
                filepath = os.path.join(root, file)
                mod_name = get_module_name(filepath, base_dir)
                is_init = file == '__init__.py'
                
                if is_init:
                    modules[mod_name] = {'id': dir_id, 'path': filepath, 'label': file, 'dir_id': dir_id, 'is_init': is_init}
                else:
                    file_id = f"file_{id_counter}"
                    modules[mod_name] = {'id': file_id, 'path': filepath, 'label': file, 'dir_id': dir_id, 'is_init': is_init}
                    id_counter += 1
                    
                    edges.append({
                        'id': f"edge_struct_{dir_id}_{file_id}",
                        'from': dir_id,
                        'to': file_id,
                        'edgeType': 'struct',
                        'color': {'color': '#111111'},
                        'dashes': False,
                        'arrows': '',
                        'smooth': False,
                        'length': 60
                    })

    added_deps = set()
    for mod_name, info in modules.items():
        lines, pub, priv, imps = parse_file(info['path'])
        
        level = folder_level_info[info['dir_id']]
        node_color = folder_colors[level % len(folder_colors)]
        
        is_root = level == 0
        is_init = info.get('is_init', False)
        
        if not is_init:
            # Calculate dynamic size based on lines of code using a logarithmic scale
            # e.g., 10 lines -> ~9px, 100 lines -> ~13px, 1000 lines -> ~17px, 3000 lines -> ~19px
            node_size = int(5 + math.log10(max(lines, 1)) * 4)
    
            nodes.append({
                'id': info['id'],
                'label': info['label'],
                'shape': 'dot',
                'size': node_size,
                'level': level,
                'isFolder': False,
                'borderWidth': 1,
                'color': {
                    'background': node_color, 
                    'border': '#111111',
                    'highlight': {'background': '#111111', 'border': '#111111'},
                    'hover': {'background': '#111111', 'border': '#111111'}
                },
                'font': {'color': '#111111', 'size': 16 if is_root else 14, 'face': 'Playfair Display, Georgia, Times New Roman, serif'},
                'info': {
                    'path': os.path.relpath(info['path'], base_dir),
                    'lines': lines,
                    'public': pub,
                    'private': priv,
                    'dir_id': info['dir_id']
                }
            })

        for imp in imps:
            for other_mod, other_info in modules.items():
                parts = other_mod.split('.')
                target_str = parts[-1]
                
                # If the target is an __init__.py, importing its parent folder name matches it
                match = False
                if target_str == '__init__' and len(parts) >= 2:
                    parent_target = parts[-2]
                    if imp.endswith(parent_target) or parent_target in imp:
                        match = True
                
                # Standard relative / absolute match
                if imp.endswith(target_str) or target_str in imp:
                    match = True
                    
                if match and info['id'] != other_info['id']:
                    edge_id = f"edge_dep_{other_info['id']}_{info['id']}"
                    if edge_id not in added_deps:
                        added_deps.add(edge_id)
                        edges.append({
                            'id': edge_id,
                            'from': other_info['id'],
                            'to': info['id'],
                            'edgeType': 'dep',
                            'arrows': { 'to': { 'enabled': True, 'scaleFactor': 0.7, 'type': 'arrow' } },
                            'color': { 'color': '#7A7A7A', 'opacity': 0.8, 'highlight': '#111111' },
                            'smooth': { 'type': 'curvedCW', 'roundness': 0.2 },
                            'dashes': [5, 5],
                            'length': 300 
                        })

    # SVG chevron icon for folders
    chevron_svg = '<svg class="chevron" viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.41z"/></svg>'

    def build_legend_html(dir_id, is_root=False):
        info = folders_info[dir_id]
        name = 'droplogic (root)' if is_root else info['name']
        color = info['color']
        
        open_attr = "open" if is_root else ""
        
        folder_icon = f'<svg class="folder-svg" viewBox="0 0 24 24" width="16" height="16" style="color:{color};"><path fill="currentColor" d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>'
        file_icon = '<svg class="folder-svg" viewBox="0 0 24 24" width="14" height="14" style="color:#111111;"><path fill="currentColor" d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>'

        # Gather files belonging to this dir
        files_in_dir = []
        for mod_name, mod_info in modules.items():
            if mod_info['dir_id'] == dir_id and not mod_info.get('is_init', False):
                files_in_dir.append(mod_info)
        
        # We also need to map the init node logically to the folder for hovering its ID
        js_events = f' onmouseenter="applyHighlight(\'{dir_id}\')" onmouseleave="applyHighlight(null)" '
        
        if not info['children'] and not files_in_dir:
            return f'<div class="legend-item leaf-item" id="legend-{dir_id}" {js_events}><div class="item-content"><span class="spacer"></span>{folder_icon}<span class="folder-name">{name}</span></div></div>'
            
        html = f'<details id="legend-{dir_id}" {open_attr}><summary {js_events}><div class="item-content">{chevron_svg}{folder_icon}<span class="folder-name">{name}</span></div></summary>'
        html += '<div class="legend-children">'
        
        for f in sorted(files_in_dir, key=lambda x: x['label']):
            f_id = f['id']
            f_js = f' onmouseenter="applyHighlight(\'{f_id}\')" onmouseleave="applyHighlight(null)" '
            html += f'<div class="legend-item leaf-item" id="legend-{f_id}" {f_js}><div class="item-content" style="padding-left:16px;">{file_icon}<span class="folder-name" style="font-size:12px;">{f["label"]}</span></div></div>'

        for child_id in sorted(info['children'], key=lambda x: folders_info[x]['name']):
            html += build_legend_html(child_id)
            
        html += '</div></details>'
        return html

    root_id = f"dir_{os.path.relpath(package_dir, base_dir).replace('/', '_')}"
    
    legend_html = '<div id="color-legend" class="mode-struct">'
    legend_html += '<div id="title-struct" class="legend-title">Folder Tree Map</div>'
    legend_html += '<div id="title-dep" class="legend-title">File Origin Folders</div>'
    legend_html += '<div class="tree-container">'
    legend_html += build_legend_html(root_id, is_root=True)
    legend_html += '</div></div>'
    
    frontmatter = "---\nhide:\n  - header\n  - footer\n  - toc\n---\n\n"

    html_template = """
<script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style type="text/css">
  .network-wrapper {
    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    z-index: 50; background: #FFF; margin: 0; padding: 0;
    font-family: "Playfair Display", Georgia, "Times New Roman", serif;
  }
  #mynetwork { width: 100%; height: 100%; background-color: #FFF; outline: none; }
  
  .md-header, .md-footer, .md-sidebar--secondary, .md-nav--secondary, .md-content__button { display: none !important; }
  .md-main__inner { margin: 0 !important; padding: 0 !important; max-width: none !important; }

  .md-sidebar--primary {
    position: fixed !important; top: 0 !important; left: 0 !important;
    width: 300px !important; height: 100vh !important; z-index: 1000 !important;
    background: #FFFFFF !important;
    border-right: 1px solid #111111 !important;
    transition: left 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: none !important;
    padding-top: 15px !important; display: block !important;
  }
  .md-sidebar--primary.closed { left: -320px !important; }
  
  .controls-top {
    position: absolute; top: 15px; left: 320px; right: 15px; 
    display: flex; justify-content: flex-start; align-items: center; gap: 15px; z-index: 100;
    pointer-events: none; transition: left 0.3s ease;
  }
  .controls-top.shifted-back { left: 15px; } 
  .controls-top > * { pointer-events: auto; }
  
  #graph-menu-btn {
    background: #FFFFFF;
    border: 1px solid #111111;
    border-radius: 0;
    padding: 8px;
    cursor: pointer;
    color: #111111;
    display: flex; align-items: center; justify-content: center; transition: all 0.2s ease;
  }
  #graph-menu-btn:hover { background: #111111; color: #FFFFFF; }
  
  .segmented-control {
    background: #FFFFFF;
    border-radius: 0;
    padding: 0;
    display: flex;
    gap: 0;
    border: 1px solid #111111;
  }
  .segmented-control input[type="radio"] { display: none; }
  .segmented-control label {
    color: #111111;
    padding: 8px 14px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .segmented-control input:checked + label {
    background: #111111;
    color: #FFF;
  }
  
  #color-legend {
    position: absolute; bottom: 15px; left: 320px; z-index: 1000;
    background: #FFFFFF;
    border: 1px solid #111111;
    border-radius: 0;
    padding: 16px;
    color: #111111;
    font-size: 13px;
    font-weight: 500;
    box-shadow: none;
    pointer-events: auto; transition: left 0.3s ease;
    max-height: 60vh; overflow-y: auto; overflow-x: hidden; min-width: 240px;
  }
  #color-legend.shifted-back { left: 15px; }
  #color-legend::-webkit-scrollbar { width: 6px; }
  #color-legend::-webkit-scrollbar-thumb { background: #111111; border-radius: 0; }
  
  #color-legend .legend-title {
    margin: 0 0 12px 0; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #111111;
    font-weight: 700;
    border-bottom: 1px solid #111111;
    padding-bottom: 8px;
  }
  
  #color-legend.mode-struct #title-dep { display: none !important; }
  #color-legend.mode-struct #title-struct { display: block !important; }
  #color-legend.mode-dep #title-struct { display: none !important; }
  #color-legend.mode-dep #title-dep { display: block !important; }

  /* OVERRIDE MKDOCS MATERIAL DEFAULT ADMONITION STYLES ON DETAILS */
  .md-typeset #color-legend details {
    background: transparent !important; border: none !important; box-shadow: none !important;
    margin: 0 !important; padding: 0 !important;
  }
  .md-typeset #color-legend details > summary::before,
  .md-typeset #color-legend details > summary::after {
    display: none !important; content: none !important; background: transparent !important;
  }
  .md-typeset #color-legend details > summary {
    background: transparent !important; padding: 0 !important; margin: 1px 0 !important;
    min-height: auto !important; box-shadow: none !important;
  }
  .md-typeset #color-legend details[open] { background: transparent !important; padding: 0 !important; }

  .tree-container { margin-top: 4px; }

  .tree-container details { margin: 0; padding: 0; }
  
  .tree-container summary, .leaf-item {
    list-style: none; /* Hide default triangle */
    outline: none; cursor: pointer; border-radius: 0;
    user-select: none; margin: 1px 0; transition: background 0.2s ease;
  }
  /* Remove default triangle in Safari/WebKit */
  .tree-container summary::-webkit-details-marker { display: none !important; }
  
  .tree-container summary:hover, .leaf-item:hover { background: #111111; }
  .tree-container summary:hover .folder-name,
  .tree-container summary:hover .chevron,
  .tree-container summary:hover .folder-svg,
  .leaf-item:hover .folder-name,
  .leaf-item:hover .folder-svg {
    color: #FFFFFF !important;
  }
  
  .item-content {
    display: flex; align-items: center; padding: 4px 6px; gap: 6px;
  }

  .chevron {
    color: #111111; transition: transform 0.2s ease; flex-shrink: 0;
  }
  
  .tree-container details[open] > summary .chevron {
    transform: rotate(90deg);
  }

  .spacer { width: 16px; flex-shrink: 0; } /* Matches chevron width for alignment */

  .folder-svg { flex-shrink: 0; display: flex; align-items: center; }
  
  .folder-name { white-space: nowrap; text-overflow: ellipsis; overflow: hidden; color: #111111; }

  .legend-children {
    margin-left: 20px;
    padding-left: 4px;
    border-left: 1px solid #111111;
  }

  /* Target Highlight */
  .legend-highlight > .item-content {
    background: #111111 !important;
    border-radius: 0;
  }
  .legend-highlight .folder-name,
  .legend-highlight .folder-svg,
  .legend-highlight .chevron { color: #FFFFFF !important; font-weight: 600; }

  /* --- INFO CARD --- */
  #node-info {
    padding: 20px;
    border: 1px solid #111111;
    border-radius: 0;
    background: #FFFFFF;
    display: none;
    color: #111111;
    box-shadow: none;
    pointer-events: none;
    font-family: "Playfair Display", Georgia, "Times New Roman", serif;
    position: absolute; z-index: 1000;
    bottom: 15px; right: 15px; top: auto; width: 280px;
  }
  #node-info h3 { margin: 0 0 15px 0; color: #111111; font-size: 1.1em; font-weight: 600; word-break: break-all;}
  .badge { display: inline-block; padding: 4px 8px; border-radius: 0; font-size: 12px; margin: 2px 4px 2px 0; font-weight: 500;}
  .badge-pub { background-color: #111111; color: #FFFFFF; border: 1px solid #111111; }
  .badge-priv { background-color: #FFFFFF; color: #111111; border: 1px solid #111111; }

  /* --- HOVER LEGEND --- */
  #hover-legend {
    position: absolute; top: 15px; right: 15px; z-index: 1000;
    background: #FFFFFF;
    border: 1px solid #111111;
    border-radius: 0;
    padding: 12px 16px;
    color: #111111;
    font-size: 13px;
    font-weight: 500;
    box-shadow: none;
    pointer-events: none; opacity: 0; transition: opacity 0.2s ease;
  }
  .hl-title { margin: 0 0 8px 0; color: #111111; font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; }
  .hl-item { display: flex; align-items: center; margin-bottom: 6px; }
  .hl-item:last-child { margin-bottom: 0; }
  .hl-color { width: 12px; height: 12px; border: 1px solid #111111; margin-right: 8px; display: inline-block; }
</style>

<div class="network-wrapper">
  <div class="controls-top">
    <button id="graph-menu-btn" title="Toggle Navigation Menu">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
        <path d="M3 6h18v2H3V6m0 5h18v2H3v-2m0 5h18v2H3v-2Z"/>
      </svg>
    </button>
    <div class="segmented-control">
      <input type="radio" name="mode" id="mode-struct" value="struct" checked>
      <label for="mode-struct">Structure</label>
      <input type="radio" name="mode" id="mode-dep" value="dep">
      <label for="mode-dep">Dependencies</label>
    </div>
  </div>
  THE_LEGEND_HTML
  <div id="hover-legend">
    <div class="hl-title">Connections</div>
    <div class="hl-item"><span class="hl-color" style="background:#111111;"></span> Child</div>
    <div class="hl-item"><span class="hl-color" style="background:#444444;"></span> Parent</div>
    <div class="hl-item"><span class="hl-color" style="background:#777777;"></span> Imports</div>
    <div class="hl-item"><span class="hl-color" style="background:#BBBBBB;"></span> Imported by</div>
  </div>
  <div id="node-info"></div>
  <div id="mynetwork"></div>
</div>

<script type="text/javascript">
  var nodesInfo = """ + json.dumps({n['id']: n.get('info', {}) for n in nodes if 'info' in n}) + """;
  var rawNodes = new vis.DataSet(""" + json.dumps(nodes) + """);
  var rawEdges = new vis.DataSet(""" + json.dumps(edges) + """);

  var currentMode = 'struct';

  var nodesView = new vis.DataView(rawNodes, {
    filter: function (item) {
      if (currentMode === 'struct') return true; 
      if (currentMode === 'dep') return !item.isFolder; 
    }
  });

  var edgesView = new vis.DataView(rawEdges, {
    filter: function (item) {
      if (currentMode === 'struct') return true; 
      if (currentMode === 'dep') return item.edgeType === 'dep'; 
    }
  });

  var container = document.getElementById('mynetwork');
  var data = { nodes: nodesView, edges: edgesView };
  
  var options = {
    interaction: { hover: true, hoverConnectedEdges: false, tooltipDelay: 100 },
    physics: {
      solver: 'forceAtlas2Based',
      forceAtlas2Based: { gravitationalConstant: -80, centralGravity: 0.01, springLength: 200, springConstant: 0.08, damping: 0.85 },
      stabilization: { iterations: 200 }
    }
  };
  
  var network = new vis.Network(container, data, options);

  // Auto-center precisely on stabilization
  network.once("stabilizationIterationsDone", function() {
      network.fit({
          animation: { duration: 1000, easingFunction: 'easeInOutQuad' }
      });
  });

  // ---------- CUSTOM HOVER SEMANTIC HIGHLIGHT ---------- //
  var originalNodes = {};
  rawNodes.forEach(function(n) {
      originalNodes[n.id] = { color: n.color, borderWidth: n.borderWidth || 1, fontColor: n.font.color };
  });
  
  var originalEdges = {};
  rawEdges.forEach(function(e) {
      originalEdges[e.id] = { color: e.color, width: e.width || 1, dashes: e.dashes };
  });

  function applyHighlight(hoveredNodeId) {
      if (!hoveredNodeId) {
          var nodeUpdates = [];
          rawNodes.forEach(function(n) {
              nodeUpdates.push({
                 id: n.id, 
                 color: originalNodes[n.id].color,
                 borderWidth: originalNodes[n.id].borderWidth,
                 font: { color: originalNodes[n.id].fontColor }
              });
          });
          rawNodes.update(nodeUpdates);
          
          var edgeUpdates = [];
          rawEdges.forEach(function(e) {
              edgeUpdates.push({
                 id: e.id, 
                 color: originalEdges[e.id].color,
                 width: originalEdges[e.id].width,
                 dashes: originalEdges[e.id].dashes
              });
          });
          rawEdges.update(edgeUpdates);
          if (document.getElementById('hover-legend')) { document.getElementById('hover-legend').style.opacity = '0'; }
          return;
      }
      
      var edgesId = network.getConnectedEdges(hoveredNodeId);
      var connectedEdges = rawEdges.get(edgesId);
      
      var children = [];
      var parents = [];
      var depsOutgoing = []; // What the hovered node imports
      var depsIncoming = []; // What imports the hovered node
      
      connectedEdges.forEach(function(edge) {
          if (edge.edgeType === 'struct') {
              if (edge.from === hoveredNodeId) children.push(edge.to);
              if (edge.to === hoveredNodeId) parents.push(edge.from);
          } else if (edge.edgeType === 'dep') {
              if (edge.from === hoveredNodeId) depsIncoming.push(edge.to);     // Hovered node is imported by edge.to
              if (edge.to === hoveredNodeId) depsOutgoing.push(edge.from);   // Hovered node imports edge.from
          }
      });
      
      // Dim non-connected, color code the tree semantic edges
      var nodeUpdates = [];
      rawNodes.forEach(function(n) {
          if (n.id === hoveredNodeId) {
              nodeUpdates.push({id: n.id}); 
          } else if (children.includes(n.id)) {
              var newColor = Object.assign({}, originalNodes[n.id].color);
              newColor.border = '#111111';
              nodeUpdates.push({id: n.id, color: newColor, borderWidth: 3, font: {color: '#111111'}});
          } else if (parents.includes(n.id)) {
              var newColor = Object.assign({}, originalNodes[n.id].color);
              newColor.border = '#444444';
              nodeUpdates.push({id: n.id, color: newColor, borderWidth: 3, font: {color: '#111111'}});
          } else if (depsOutgoing.includes(n.id)) {
              var newColor = Object.assign({}, originalNodes[n.id].color);
              newColor.border = '#777777';
              nodeUpdates.push({id: n.id, color: newColor, borderWidth: 3, font: {color: '#111111'}});
          } else if (depsIncoming.includes(n.id)) {
              var newColor = Object.assign({}, originalNodes[n.id].color);
              newColor.border = '#BBBBBB';
              nodeUpdates.push({id: n.id, color: newColor, borderWidth: 3, font: {color: '#111111'}});
          } else {
              var newColor = Object.assign({}, originalNodes[n.id].color);
              newColor.background = '#F4F4F4';
              newColor.border = '#D8D8D8';
              nodeUpdates.push({id: n.id, color: newColor, borderWidth: 1, font: {color: '#9A9A9A'}});
          }
      });
      rawNodes.update(nodeUpdates);
      
      var edgeUpdates = [];
      rawEdges.forEach(function(e) {
          if (edgesId.includes(e.id)) {
             var edgeColor = '#111111';
             var edgeDashes = false;
             if (e.edgeType === 'struct') {
                 if (e.from === hoveredNodeId) edgeColor = '#111111';
                 if (e.to === hoveredNodeId) edgeColor = '#444444';
             } else {
                 if (e.to === hoveredNodeId) {
                     edgeColor = '#777777';
                     edgeDashes = [4, 4];
                 }
                 if (e.from === hoveredNodeId) {
                     edgeColor = '#BBBBBB';
                     edgeDashes = [2, 6];
                 }
             }
             edgeUpdates.push({id: e.id, width: 3, dashes: edgeDashes, color: {color: edgeColor}});
          } else {
             edgeUpdates.push({id: e.id, width: 1, color: {color: '#D8D8D8'}, dashes: originalEdges[e.id].dashes});
          }
      });
      rawEdges.update(edgeUpdates);
      if (document.getElementById('hover-legend')) { document.getElementById('hover-legend').style.opacity = '1'; }
  }

  var isDragging = false;
  network.on("dragStart", function (params) {
      if (params.nodes.length > 0) {
          isDragging = true;
          applyHighlight(null);
      }
  });
  network.on("dragEnd", function (params) {
      isDragging = false;
  });

  network.on("hoverNode", function (params) { 
      if (!isDragging) {
          applyHighlight(params.node); 
      }
  });
  network.on("blurNode", function (params) { 
      if (!isDragging) {
          applyHighlight(null); 
      }
  });


  var menuBtn = document.getElementById('graph-menu-btn');
  var controlsTop = document.querySelector('.controls-top');
  var colorLegend = document.getElementById('color-legend');
  
  menuBtn.addEventListener('click', function(e) {
    e.stopPropagation();
    var sidebar = document.querySelector('.md-sidebar--primary');
    if (sidebar) {
      sidebar.classList.toggle('closed');
      if (sidebar.classList.contains('closed')) {
        controlsTop.classList.add('shifted-back');
        if(colorLegend) colorLegend.classList.add('shifted-back');
      } else {
        controlsTop.classList.remove('shifted-back');
        if(colorLegend) colorLegend.classList.remove('shifted-back');
      }
    }
  });
  
  document.querySelectorAll('input[name="mode"]').forEach((radio) => {
    radio.addEventListener('change', function(e) {
      currentMode = e.target.value;
      if (colorLegend) {
         colorLegend.classList.remove('mode-struct', 'mode-dep');
         colorLegend.classList.add('mode-' + currentMode);
      }
      
      var sizeUpdates = [];
      rawNodes.forEach(function(node) {
          if(!node.isFolder && node.level === 0) {
              // we used to redefine sizes, but we now calculate dynamic sizes from LOC
          }
      });
      if(sizeUpdates.length > 0) rawNodes.update(sizeUpdates);

      nodesView.refresh();
      edgesView.refresh();
      

      
      if(currentMode === 'dep') {
         setTimeout(() => network.fit({animation: {duration: 800, easingFunction: 'easeInOutQuad'}}), 200);
      }
      applyHighlight(null); 
    });
  });

  function clearLegendHighlights() {
    document.querySelectorAll('#color-legend .legend-highlight').forEach(el => {
       el.classList.remove('legend-highlight');
    });
  }

  network.on("click", function (params) {
    clearLegendHighlights();
    
    if (params.nodes.length > 0) {
      var nodeId = params.nodes[0];
      var node = rawNodes.get(nodeId);
      
      var dirId = node.isFolder ? node.id : (nodesInfo[nodeId] ? nodesInfo[nodeId].dir_id : null);
      if (dirId) {
         let legendTarget = document.getElementById('legend-' + dirId);
         if (legendTarget) {
            if(legendTarget.tagName.toLowerCase() === 'details') {
               legendTarget.querySelector('summary').classList.add('legend-highlight');
            } else {
               legendTarget.classList.add('legend-highlight');
            }
            
            let parent = legendTarget.parentElement;
            while(parent && parent.id !== 'color-legend') {
               if(parent.tagName.toLowerCase() === 'details') {
                  parent.open = true;
               }
               parent = parent.parentElement;
            }
            legendTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
         }
      }

      if (!node.isFolder && nodesInfo[nodeId]) {
         var info = nodesInfo[nodeId];
         var infoDiv = document.getElementById('node-info');
         
         var pubHtml = info.public.map(f => '<span class="badge badge-pub">' + f + '</span>').join('');
         var privHtml = info.private.map(f => '<span class="badge badge-priv">' + f + '</span>').join('');
         
         html = '<h3>' + info.path + ' <span style="color:#666666; font-weight:400; font-size:14px;">(' + info.lines + ' lines)</span></h3>';
         if (info.public.length > 0) html += '<p style="margin: 8px 0 4px 0; font-size: 14px;"><strong>Public Methods</strong><br>' + pubHtml + '</p>';
         if (info.private.length > 0) html += '<p style="margin: 8px 0 4px 0; font-size: 14px;"><strong>Private</strong><br>' + privHtml + '</p>';
         
         infoDiv.innerHTML = html;
         infoDiv.style.display = 'block';
      } else {
         document.getElementById('node-info').style.display = 'none';
      }
    } else {
      document.getElementById('node-info').style.display = 'none';
    }
  });
</script>
"""
    final_content = frontmatter + html_template.replace("THE_LEGEND_HTML", legend_html)

    with open(os.path.join(docs_dir, 'repository_structure.en.md'), 'w', encoding='utf-8') as f:
        f.write(final_content)
        
    with open(os.path.join(docs_dir, 'repository_structure.es.md'), 'w', encoding='utf-8') as f:
        f.write(final_content)
        
    print("Graph updated.")

if __name__ == '__main__':
    generate()
