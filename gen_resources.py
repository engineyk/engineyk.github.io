# _posts/
# ├── 渲染类/                    → <h3>渲染类</h3>
# │   ├── 2022-03-04-PBR.md     →   <li><a href="/2022/03/04/PBR">PBR</a></li>
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

    return title, url, date_str


def scan_posts(posts_dir: str):
    """
    Scan posts directory.
    Returns: dict { category_name: [ (title, url, date), ... ] }
    Uncategorized files (directly in _posts root) go to 'Other' category.
    """
    root = Path(posts_dir)
    categories = {}
    root_files = []

    if not root.exists():
        print(f"[ERROR] Directory not found: {posts_dir}")
        return categories

    for item in sorted(root.iterdir()):
        if item.is_dir():
            # Subdirectory as category
            cat_name = item.name
            files = []
            for f in sorted(item.iterdir()):
                if f.is_file() and f.suffix.lower() in ('.md', '.markdown', '.html'):
                    title, url, date_str = parse_post_file(f)
                    files.append((title, url, date_str))
            if files:
                categories[cat_name] = files
        elif item.is_file() and item.suffix.lower() in ('.md', '.markdown', '.html'):
            # Files directly in _posts root
            title, url, date_str = parse_post_file(item)
            root_files.append((title, url, date_str))

    # Add root files as 'Other' category
    if root_files:
        categories['Other'] = root_files

    return categories


def generate_html(categories: dict) -> str:
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

    toc_index = 0
    for cat_name, files in categories.items():
        lines.append(f'<h3 id="toc_{toc_index}">{cat_name}</h3>')
        lines.append('')
        lines.append('<ul>')
        for title, url, date_str in files:
            date_hint = f" <small>({date_str})</small>" if date_str else ""
            lines.append(f'<li><a href="{url}">{title}</a>{date_hint}</li>')
        lines.append('</ul>')
        lines.append('')
        toc_index += 1

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
    categories = scan_posts(POSTS_DIR)

    if not categories:
        print("[WARN] No posts found.")
        return

    print(f"Found {len(categories)} categories:")
    for cat, files in categories.items():
        print(f"  [{cat}] {len(files)} files")
        for title, url, date_str in files:
            print(f"    - {title} ({date_str})")

    html_content = generate_html(categories)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"\n[OK] Generated: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
