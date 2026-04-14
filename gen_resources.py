# _posts/
# ├── 渲染类/                    → <h3>渲染类</h3>
# │   ├── PBR/                  →   <h4>PBR</h4>
# │   │   └── 2022-03-04-PBR.md →     <li><a href="/2022/03/04/PBR">PBR</a></li>
# │   └── 2023-08-10-URP.md     →   <li><a href="/2023/08/10/URP">URP</a></li>
# ├── Unreal Game Play/
# │   └── 2023-04-09-GAS.md
# └── 2024-01-10-SomePost.md    → 无子目录的文件归入 "Other" 分类


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scan W:\git\engineyk.github.io\_posts directory,
generate resources.html with subdirectories as categories
and files as list items.
"""

import os
import re
from pathlib import Path

# Config
POSTS_DIR = r"W:\git\engineyk.github.io\_posts"
OUTPUT_FILE = r"W:\git\engineyk.github.io\resources.html"

# Jekyll date prefix pattern: YYYY-MM-DD-title.md
DATE_PATTERN = re.compile(r'^(\d{4})-(\d{2})-(\d{2})-(.+)$')


def parse_post_file(filepath: Path):
    """
    Parse post file, extract title and date.
    Priority: YAML front matter title > filename
    """
    title = None
    date_str = None
    subtitle = None

    # Try to read YAML front matter
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract front matter between ---
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            fm = fm_match.group(1)
            # Extract title
            title_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', fm, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()
            # Extract subtitle
            subtitle_match = re.search(r'^subtitle:\s*["\']?(.+?)["\']?\s*$', fm, re.MULTILINE)
            if subtitle_match:
                subtitle = subtitle_match.group(1).strip()
            # Extract date
            date_match = re.search(r'^date:\s*(.+?)\s*$', fm, re.MULTILINE)
            if date_match:
                date_str = date_match.group(1).strip()[:10]  # Keep YYYY-MM-DD
    except Exception:
        pass

    # Parse filename: YYYY-MM-DD-slug.md
    stem = filepath.stem  # filename without extension
    m = DATE_PATTERN.match(stem)
    if m:
        year, month, day, slug = m.group(1), m.group(2), m.group(3), m.group(4)
        if not date_str:
            date_str = f"{year}/{month}/{day}"
        if not title:
            # Use slug as title, replace hyphens with spaces
            title = slug.replace('-', ' ')
        # Jekyll post URL: /YYYY/MM/DD/slug/
        url = "{{{{site.baseurl}}}}/{year}/{month}/{day}/{slug}".format(
            year=year, month=month, day=day, slug=slug
        )
    else:
        # No date prefix, use filename as slug
        slug = stem
        if not title:
            title = slug.replace('-', ' ')
        url = "{{{{site.baseurl}}}}/{slug}".format(slug=slug)
        if not date_str:
            date_str = ""

    return title, url, date_str, subtitle


def scan_posts(posts_dir: str):
    """
    Scan posts directory recursively, build a tree structure.
    Returns a tree node dict:
    {
        'files': [(title, url, date), ...],   # files directly in this dir
        'children': {                          # subdirectories
            'subdir_name': { 'files': [...], 'children': {...} },
            ...
        }
    }
    """
    root = Path(posts_dir)

    if not root.exists():
        print(f"[ERROR] Directory not found: {posts_dir}")
        return {'files': [], 'children': {}}

    def scan_dir(directory: Path) -> dict:
        """Recursively scan directory, return tree node."""
        node = {'files': [], 'children': {}}
        for item in sorted(directory.iterdir()):
            if item.is_dir():
                node['children'][item.name] = scan_dir(item)
            elif item.is_file() and item.suffix.lower() in ('.md', '.markdown', '.html'):
                title, url, date_str, subtitle = parse_post_file(item)
                node['files'].append((title, url, date_str, subtitle))
        return node

    return scan_dir(root)


def generate_html(tree: dict) -> str:
    """
    Generate resources.html content based on existing template format.
    """
    lines = []

    # File header (Jekyll front matter)
    lines.append('---')
    lines.append('layout: page')
    lines.append('title: "Resources"')
    lines.append('description: "目录"')
    lines.append('header-img: "img/post-bg-rwd.jpg"')
    lines.append('---')
    lines.append('')
    lines.append('<div class="zh post-container">')
    lines.append('')
    lines.append('    <!--copied from markdown -->')
    lines.append('    <blockquote><p>每天只要15分钟，一个月就能掌握<br>')
    lines.append('    学一点儿是一点儿，不用也不会忘</p></blockquote>')
    lines.append('')
    lines.append('    <p></p>')
    lines.append('        ')

    toc_counter = [0]  # use list to allow mutation in nested function
    h3_counter = [0]   # counter for top-level (depth=0) sections

    # Chinese number labels for top-level sections
    CN_NUMS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
               '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十']

    # Heading tags by depth: depth=0 -> h3, depth=1 -> h4, depth>=2 -> h5
    def heading_tag(depth):
        tags = ['h3', 'h4', 'h5']
        return tags[min(depth, len(tags) - 1)]

    def render_node(node: dict, name: str = None, depth: int = 0):
        """Recursively render tree node into HTML lines."""
        # Render category heading (skip for root node)
        if name is not None:
            tag = heading_tag(depth)
            indent = '    ' * (depth + 1)  # h3->4sp, h4->8sp, h5->12sp
            if depth == 0:
                # Add horizontal rule before each top-level section
                lines.append(f'{indent}<hr>')
                # Add Chinese number label
                cn_num = CN_NUMS[h3_counter[0]] if h3_counter[0] < len(CN_NUMS) else str(h3_counter[0] + 1)
                lines.append(f'{indent}<{tag} id="toc_{toc_counter[0]}">{cn_num}、{name}</{tag}>')
                h3_counter[0] += 1
            else:
                lines.append(f'{indent}<{tag} id="toc_{toc_counter[0]}">{name}</{tag}>')
            lines.append('')
            toc_counter[0] += 1

        # Render files directly in this node
        if node['files']:
            # ul indent: one level deeper than heading
            ul_indent = '    ' * (depth + 2)
            lines.append(f'{ul_indent}<ul>')
            for title, url, date_str, subtitle in node['files']:
                date_hint = f" <small>({date_str})</small>" if date_str else ""
                date_hint = f""
                subtitle_hint = f" <small>- {subtitle}</small>" if subtitle else ""
                lines.append(f'{ul_indent}    <li><a href="{url}">{title}</a>{subtitle_hint}{date_hint}</li>')
            lines.append(f'{ul_indent}</ul>')
            lines.append('')

        # Render subdirectories recursively
        for child_name, child_node in node['children'].items():
            render_node(child_node, child_name, depth + 1)

    # Render root-level files as 'Other'
    if tree['files']:
        other_node = {'files': tree['files'], 'children': {}}
        render_node(other_node, 'Other', 0)

    # Render top-level subdirectories
    for cat_name, cat_node in tree['children'].items():
        render_node(cat_node, cat_name, 0)

    lines.append('')
    lines.append('</div>')
    lines.append('')
    lines.append('')
    lines.append('')
    # Language switch script (keep original)
    lines.append('<!-- Handle Language Change -->')
    lines.append('<script type="text/javascript">')
    lines.append('    // get nodes')
    lines.append('    var $zh = document.querySelector(".zh");')
    lines.append('    var $en = document.querySelector(".en");')
    lines.append('    var $select = document.querySelector("select");')
    lines.append('')
    lines.append('    // bind hashchange event')
    lines.append('    window.addEventListener(\'hashchange\', _render);')
    lines.append('')
    lines.append('    // handle render')
    lines.append('    function _render(){')
    lines.append('        var _hash = window.location.hash;')
    lines.append('        // en')
    lines.append('        if(_hash == "#en"){')
    lines.append('            $select.selectedIndex = 1;')
    lines.append('            $en.style.display = "block";')
    lines.append('            $zh.style.display = "none";')
    lines.append('        // zh by default')
    lines.append('        }else{')
    lines.append('            // not trigger onChange, otherwise cause a loop call.')
    lines.append('            $select.selectedIndex = 0;')
    lines.append('            $zh.style.display = "block";')
    lines.append('            $en.style.display = "none";')
    lines.append('        }')
    lines.append('    }')
    lines.append('')
    lines.append('    // handle select change')
    lines.append('    function onLanChange(index){')
    lines.append('        if(index == 0){')
    lines.append('            window.location.hash = "#zh"')
    lines.append('        } else {')
    lines.append('            window.location.hash = "#en"')
    lines.append('        }')
    lines.append('    }')
    lines.append('')
    lines.append('    // init')
    lines.append('    _render();')
    lines.append('</script>')

    return '\n'.join(lines) + '\r\n'


def main():
    print(f"Scanning: {POSTS_DIR}")
    tree = scan_posts(POSTS_DIR)

    total_files = 0
    def count_files(node):
        nonlocal total_files
        total_files += len(node['files'])
        for child in node['children'].values():
            count_files(child)
    count_files(tree)

    if total_files == 0:
        print("[WARN] No posts found.")
        return

    def print_tree(node, name=None, indent=0):
        prefix = '  ' * indent
        if name:
            print(f"{prefix}[{name}] {len(node['files'])} files")
        for title, url, date_str, subtitle in node['files']:
            subtitle_str = f" - {subtitle}" if subtitle else ""
            print(f"{prefix}  - {title}{subtitle_str} ({date_str})")
        for child_name, child_node in node['children'].items():
            print_tree(child_node, child_name, indent + 1)

    print(f"Found {total_files} posts:")
    print_tree(tree)

    html_content = generate_html(tree)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"\n[OK] Generated: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
