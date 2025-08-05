#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import argparse
import re
import os
import time
from collections import defaultdict, Counter
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode
from bs4 import BeautifulSoup
import sys

REPLACE_PATTERNS = [
    r"/\?C=S;O=A$",
    r"/\?C=D;O=A$",
    r"/\?C=M;O=A$",
    r"/\?C=N;O=D$"
]

LISTING_ARTIFACT_PATTERNS = [
    r"\?C=S;O=A$",
    r"\?C=D;O=A$",
    r"\?C=M;O=A$",
    r"\?C=N;O=D$",
    r"\?C=N;O=A$",
    r"\?C=M;O=D$",
    r"\?C=D;O=D$",
    r"\?C=S;O=D$"
]

EXT_TO_NAME = {
    "php": "PHP", "html": "HTML", "htm": "HTML", "xhtml": "HTML5", "js": "JS",
    "css": "CSS", "png": "PNG", "jpg": "JPG", "jpeg": "JPG", "gif": "GIF",
    "svg": "SVG", "bmp": "BMP", "ico": "ICO", "json": "JSON", "txt": "TXT",
    "pdf": "PDF", "zip": "ZIP", "rar": "RAR", "7z": "7Z", "gz": "GZ", "tar": "TAR",
    "mp3": "MP3", "mp4": "MP4", "avi": "AVI", "mov": "MOV", "webm": "WEBM"
}

def normalize_url(url):
    parsed = urlparse(url)
    path = re.sub(r'/+', '/', parsed.path)
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/')
    qs = urlencode(sorted(parse_qsl(parsed.query)))
    normalized = urlunparse((parsed.scheme, parsed.netloc, path, '', qs, ''))
    return normalized

def clean_txt_url(url):
    for pat in REPLACE_PATTERNS:
        url = re.sub(pat, "/", url)
    return url

def is_listing_artifact(url):
    for pat in LISTING_ARTIFACT_PATTERNS:
        if re.search(pat, url):
            return True
    return False

def is_allowed_subdomain(url_netloc, root_domain):
    return url_netloc == root_domain or url_netloc.endswith('.' + root_domain)

def should_ignore_listing(url):
    IGNORE = [
        '/logout', '/deconnexion', '/logoff', '/signout', '/disconnect',
        '/log-out', '/user/logout'
    ]
    for ign in IGNORE:
        if ign in url:
            return True
    return False

def is_logout_url(url):
    url_lower = url.lower()
    LOGOUT_WORDS = [
        'logout', 'deconnexion', 'logoff', 'signout', 'disconnect'
    ]
    for word in LOGOUT_WORDS:
        if word in url_lower:
            return True
    return False

def should_crawl_file(url, crawl_all):
    if crawl_all:
        return True
    STATIC_EXT = [
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.ico', '.css', '.js',
        '.woff', '.woff2', '.ttf', '.eot', '.mp3', '.mp4', '.m4a', '.ogg', '.webm',
        '.avi', '.mov', '.pdf', '.zip', '.tar', '.gz', '.bz2', '.rar', '.7z', '.exe',
        '.dmg', '.iso', '.apk', '.msi', '.csv', '.xls', '.xlsx', '.doc', '.docx',
        '.ppt', '.pptx'
    ]
    for ext in STATIC_EXT:
        if url.lower().split('?',1)[0].endswith(ext):
            return False
    return True

def extract_hrefs_and_forms(html, base_url, root_domain):
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"Failed to parse {base_url}: {e}")
        return set(), set(), []

    hrefs = set()
    hrefs_no_ext = set()
    forms_found = []

    tag_attr_pairs = [
        ('a', 'href'),
        ('link', 'href'),
        ('script', 'src'),
        ('img', 'src'),
        ('source', 'src'),
        ('iframe', 'src'),
        ('embed', 'src'),
        ('object', 'data'),
        ('video', 'src'),
        ('audio', 'src'),
        ('track', 'src'),
        ('form', 'action'),
        ('input', 'src'),
        ('frame', 'src'),
    ]
    # 1. Extraire tous les liens href (GET par défaut)
    for tag, attr in tag_attr_pairs:
        for node in soup.find_all(tag):
            url = node.get(attr)
            if url:
                full_url = urljoin(base_url, url)
                parsed = urlparse(full_url)
                if (
                    parsed.scheme in ["http", "https"]
                    and is_allowed_subdomain(parsed.netloc, root_domain)
                    and parsed.netloc
                    and full_url.split('#')[0] != ""
                    and not full_url.strip() == "https://"
                    and not should_ignore_listing(full_url)
                    and not is_listing_artifact(full_url)
                ):
                    clean_url = full_url.split('#')[0]
                    # S'il s'agit d'un <form>, on traitera la méthode plus bas !
                    if tag == 'form':
                        continue
                    hrefs.add((clean_url, "GET"))
                    path = parsed.path
                    filename = path.rstrip('/').split('/')[-1]
                    if (filename and '.' not in filename and filename != '') or (path.endswith('/') and path != '/'):
                        hrefs_no_ext.add(clean_url)

    # 2. Extraire tous les <form> (POST, mais aussi GET si spécifié)
    for form in soup.find_all('form'):
        method = form.get('method', '').lower()
        if not method:
            method = 'get'  # HTML default
        action = form.get('action', '')
        form_url = urljoin(base_url, action) if action else base_url
        if (
            urlparse(form_url).scheme in ["http", "https"]
            and is_allowed_subdomain(urlparse(form_url).netloc, root_domain)
            and not should_ignore_listing(form_url)
            and not is_listing_artifact(form_url)
        ):
            params = []
            for input_tag in form.find_all('input'):
                name = input_tag.get('name')
                value = input_tag.get('value', '')
                if name:
                    name = str(name)
                    value = str(value)
                    if value != '':
                        params.append(f"{name}={value}")
                    else:
                        params.append(name)
            for textarea in form.find_all('textarea'):
                name = textarea.get('name')
                value = textarea.text
                if name:
                    name = str(name)
                    value = str(value)
                    if value.strip() != '':
                        params.append(f"{name}={value.strip()}")
                    else:
                        params.append(name)
            for select in form.find_all('select'):
                name = select.get('name')
                value = ''
                opt = select.find('option', selected=True)
                if opt:
                    value = str(opt.get('value', ''))
                elif select.find('option'):
                    value = str(select.find('option').get('value',''))
                if name:
                    name = str(name)
                    if value != '':
                        params.append(f"{name}={value}")
                    else:
                        params.append(name)
            forms_found.append({
                'url': form_url,
                'params': params,
                'method': method.upper()
            })
            hrefs.add((form_url, method.upper()))
            path = urlparse(form_url).path
            filename = path.rstrip('/').split('/')[-1]
            if (filename and '.' not in filename and filename != '') or (path.endswith('/') and path != '/'):
                hrefs_no_ext.add(form_url)

    hrefs = set(tuple(x[:2]) for x in hrefs if isinstance(x, (tuple, list)) and len(x) >= 2)
    return hrefs, hrefs_no_ext, forms_found

def get_expected_method_and_params(url, found_forms):
    # Ignore params for listing artifacts
    if is_listing_artifact(url):
        return "GET", None
    for form in found_forms:
        if normalize_url(form['url']) == normalize_url(url):
            return form.get('method', 'POST'), form['params']
    if '?' in url:
        # Only return params if not a listing artifact
        if is_listing_artifact(url):
            return "GET", None
        params = []
        query = urlparse(url).query
        for k, v in parse_qsl(query):
            if v:
                params.append(f"{k}={v}")
            else:
                params.append(k)
        return "GET", params if params else None
    return "GET", None

def format_params(method, params):
    if not params:
        return ""
    method = method.upper()
    joined = []
    for p in params:
        if '=' in p:
            k, v = p.split("=", 1)
            joined.append(f"{k}={v}")
        else:
            joined.append(p)
    return f"(POST) {' | '.join(joined)}" if method == "POST" else f"(GET) {' | '.join(joined)}"

def print_silent_status(start_time, page_count, get_params_count, post_params_count):
    elapsed = int(time.time() - start_time)
    sys.stdout.write(
        f"\r[Timer: {elapsed}s] Pages: {page_count} | GET Params: {get_params_count} | POST Params: {post_params_count}"
    )
    sys.stdout.flush()

def get_file_extension(url):
    parsed = urlparse(url)
    basename = os.path.basename(parsed.path)
    if '.' in basename:
        ext = basename.split('.')[-1].lower()
        return ext
    return ""

def get_file_folder(url):
    parsed = urlparse(url)
    path = parsed.path
    if path.endswith('/'):
        folder = path
    else:
        folder = os.path.dirname(path) + '/'
    return folder

def crawl(website, depth_max, root_domain, output_file_brut, output_file_info, cookie=None, crawl_all=False, silent=False):
    visited = set()
    to_visit = []
    detected_logout_urls = set()
    all_no_ext_links = set()
    crawl_report = []
    found_forms = []
    get_params_count = 0
    post_params_count = 0
    page_count = 0

    # Sets to avoid duplicates in output
    written_txt_urls = set()
    written_info_lines = set()

    # For summary stats
    ext_counter = Counter()
    folder_counter = Counter()
    get_param_urls = defaultdict(list)  # param_name: [urls]
    post_param_urls = defaultdict(list) # param_name: [urls]

    session = requests.Session()
    if cookie:
        cookies_dict = {}
        for c in cookie.split(';'):
            if '=' in c:
                k, v = c.strip().split('=', 1)
                cookies_dict[k] = v
        session.cookies.update(cookies_dict)

    start_url_norm = normalize_url(website)
    to_visit.append((start_url_norm, 1, 'GET', None))

    all_found_forms = []
    start_time = time.time()

    while to_visit:
        current_url, depth, method, post_params = to_visit.pop(0)
        current_url_norm = normalize_url(current_url)
        # Filter out listing artifact URLs everywhere
        if is_listing_artifact(current_url):
            continue
        if not should_crawl_file(current_url, crawl_all):
            continue
        if (current_url_norm, method) in visited or depth > depth_max:
            continue
        if not silent:
            print(f"Crawling ({depth}/{depth_max}): {current_url} [{method}]")
        visited.add((current_url_norm, method))
        page_count += 1

        # Correction : transformer post_params (list) en dict pour requests.post()
        if method == 'POST' and post_params is not None:
            post_dict = {}
            for p in post_params:
                if "=" in p:
                    k, v = p.split("=", 1)
                    post_dict[k] = v
                else:
                    post_dict[p] = ""
            post_params = post_dict

        try:
            if method == 'GET':
                resp = session.get(current_url, allow_redirects=True, timeout=10, verify=False)
            elif method == 'POST':
                resp = session.post(current_url, data=post_params, allow_redirects=True, timeout=10, verify=False)
            else:
                continue
        except Exception as e:
            if not silent:
                print(f"Error on {current_url}: {e}")
            continue

        status = resp.status_code
        size = len(resp.content)
        crawl_report.append({
            "url": current_url,
            "method": method,
            "depth": depth,
            "status": status,
            "size": size,
            "post_params": post_params if method == 'POST' else None
        })

        # Fichier .txt = uniquement les URLs (une par ligne, nettoyée, sans doublon)
        clean_url_txt = clean_txt_url(current_url)
        if clean_url_txt not in written_txt_urls:
            with open(output_file_brut, 'a', encoding='utf-8') as f:
                f.write(f"{clean_url_txt}\n")
            written_txt_urls.add(clean_url_txt)

        # Pour les stats d'extension/folders
        ext = get_file_extension(current_url)
        if ext:
            ext_counter[ext] += 1
        folder = get_file_folder(current_url)
        if folder:
            folder_counter[folder] += 1

        # Pour les stats de paramètres GET/POST
        expected_method, expected_params = get_expected_method_and_params(current_url, all_found_forms)
        if expected_method == "GET" and expected_params:
            get_params_count += len(expected_params)
            for p in expected_params:
                pname = p.split('=')[0] if '=' in p else p
                get_param_urls[pname].append(current_url)
        if expected_method == "POST" and expected_params:
            post_params_count += len(expected_params)
            for p in expected_params:
                pname = p.split('=')[0] if '=' in p else p
                post_param_urls[pname].append(current_url)
        if silent:
            print_silent_status(start_time, page_count, get_params_count, post_params_count)

        # Pour info.txt, on veut tout sur une ligne, avec params explicites, sans doublon
        params_str = format_params(expected_method, expected_params)
        params_field = f" | Params: {params_str}" if params_str else ""
        info_line = f"URL: {current_url} | Method: {method}{params_field} | Status: {status} | Size: {size}"
        if info_line not in written_info_lines:
            with open(output_file_info, 'a', encoding='utf-8') as f:
                f.write(info_line + "\n")
            written_info_lines.add(info_line)

        if resp.headers.get('content-type', '').startswith('text/html'):
            html = resp.text
            hrefs, hrefs_no_ext, forms_found = extract_hrefs_and_forms(html, current_url, root_domain)
            all_no_ext_links.update(hrefs_no_ext)
            all_found_forms.extend([dict(f, depth=depth) for f in forms_found])

            hrefs = set(tuple(x[:2]) for x in hrefs if isinstance(x, (tuple, list)) and len(x) >= 2)

            for item in hrefs:
                if not isinstance(item, tuple) or len(item) != 2:
                    continue
                h, m = item
                h_norm = normalize_url(h)
                # Filter out listing artifacts in hrefs
                if is_logout_url(h) or should_ignore_listing(h) or is_listing_artifact(h):
                    detected_logout_urls.add(h)
                    continue
                if should_crawl_file(h, crawl_all):
                    already_seen = ((h_norm, m) in visited or any(normalize_url(x[0]) == h_norm and x[2] == m for x in to_visit))
                    if not already_seen:
                        params = None
                        if m == "POST":
                            for form_obj in forms_found:
                                if normalize_url(form_obj['url']) == h_norm and form_obj.get('method', 'POST') == "POST":
                                    params = form_obj.get('params', [])
                                    break
                        to_visit.append((h, depth+1, m, params))
                    parsed_h = urlparse(h)
                    dir_path = os.path.dirname(parsed_h.path)
                    if dir_path and not dir_path.endswith('/'):
                        dir_path += '/'
                    dir_url = f"{parsed_h.scheme}://{parsed_h.netloc}{dir_path}"
                    dir_url_norm = normalize_url(dir_url)
                    already_seen_dir = ((dir_url_norm, m) in visited or any(normalize_url(x[0]) == dir_url_norm and x[2] == m for x in to_visit))
                    if dir_path and not already_seen_dir and not should_ignore_listing(dir_url) and not is_listing_artifact(dir_url):
                        to_visit.append((dir_url, depth+1, m, None))

            for form in forms_found:
                found_forms.append({
                    "url": form['url'],
                    "params": form['params'],
                    "method": form.get('method', 'POST'),
                    "depth": depth
                })

    if silent:
        # Print final status line
        print_silent_status(start_time, page_count, get_params_count, post_params_count)
        print()  # Newline after last status

    # Compute summary lines
    total_files = sum(ext_counter.values())
    ext_summary = []
    for ext in sorted(ext_counter, key=lambda k: (-ext_counter[k], k)):
        name = EXT_TO_NAME.get(ext, ext.upper())
        ext_summary.append(f"{name}: {ext_counter[ext]}")
    ext_summary_str = " | ".join(ext_summary)
    ext_stats_line = f"Detected files: {total_files} | {ext_summary_str}"

    # Top 5 folders (non-recursive)
    folder_top = folder_counter.most_common(5)
    folder_stats_line = "Top 5 folders (most files, not recursive): " + " | ".join(f"{folder} ({count})" for folder, count in folder_top)

    # GET params & POST params summary lines
    get_params_line = "GET parameters:\n"
    for param, urls in sorted(get_param_urls.items()):
        urlset = set(urls)
        get_params_line += f"  {param}: {', '.join(sorted(urlset))}\n"

    post_params_line = "POST parameters:\n"
    for param, urls in sorted(post_param_urls.items()):
        urlset = set(urls)
        post_params_line += f"  {param}: {', '.join(sorted(urlset))}\n"

    # Read all info lines
    with open(output_file_info, 'r', encoding='utf-8') as f:
        info_lines = f.readlines()

    # Compose timer/status line for top of file (even in silent mode)
    elapsed = int(time.time() - start_time)
    timer_status_line = f"[Timer: {elapsed}s] Pages: {page_count} | GET Params: {get_params_count} | POST Params: {post_params_count}"

    # Rewrite the info.txt file with summary lines at the top
    with open(output_file_info, 'w', encoding='utf-8') as f:
        f.write(timer_status_line + "\n")
        f.write(ext_stats_line + "\n")
        f.write(folder_stats_line + "\n")
        f.write(get_params_line)
        f.write(post_params_line)
        f.write("\n")
        for line in info_lines:
            f.write(line)

    if not silent:
        print("\n--- GLOBAL CRAWL REPORT ---")
        for entry in crawl_report:
            expected_method, params = get_expected_method_and_params(entry["url"], all_found_forms)
            params_str = format_params(expected_method, params)
            params_field = f" | Params: {params_str}" if params_str else ""
            out = f'URL: {entry["url"]} | Method: {entry["method"]}{params_field} | Status: {entry["status"]} | Size: {entry["size"]}'
            print(out)

        print("\n--- FOUND POST FORMS ---")
        already_seen_forms = set()
        for form in all_found_forms:
            key = (normalize_url(form['url']), ','.join(form['params']) if form['params'] else '', form['depth'])
            if key in already_seen_forms:
                continue
            already_seen_forms.add(key)
            params_str = ', '.join(form['params']) if form['params'] else '(no parameters)'
            print(f"Found {form.get('method','POST')} form URL: {form['url']} | Expected parameters: {params_str} | Depth: {form['depth']}")

    print(f"\nOutput written to: {output_file_brut}, {output_file_info}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--website', required=True, help='URL of the site to crawl')
    parser.add_argument('--depth', type=int, default=5, help='Maximum depth')
    parser.add_argument('--output', required=True, help='Output file (basename, 2 files will be created)')
    parser.add_argument('--cookie', default=None, help='Cookies to use for the session')
    parser.add_argument('--all', action='store_true', help='Include static files')
    parser.add_argument('--silent', action='store_true', help='Silent mode: only status line, timer, params/pages count')
    args = parser.parse_args()

    website = args.website.rstrip('/')
    root_domain = urlparse(website).netloc

    tstamp = time.strftime('%Y%m%d_%H%M%S')
    output_file_brut = f"{args.output}/{tstamp}-{root_domain}.txt"
    output_file_info = f"{args.output}/{tstamp}-{root_domain}_info.txt"

    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

    crawl(website, args.depth, root_domain, output_file_brut, output_file_info, args.cookie, args.all, args.silent)
