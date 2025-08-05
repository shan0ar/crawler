#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import argparse
import re
import os
import time
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode
from bs4 import BeautifulSoup

def normalize_url(url):
    """Normalize URL to avoid duplicates (remove trailing slashes except root, sort query params)"""
    parsed = urlparse(url)
    path = re.sub(r'/+', '/', parsed.path)
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/')
    qs = urlencode(sorted(parse_qsl(parsed.query)))
    normalized = urlunparse((parsed.scheme, parsed.netloc, path, '', qs, ''))
    return normalized

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
        # On ignore les fichiers statiques SANS --all
        if url.lower().split('?',1)[0].endswith(ext):
            return False
    return True

def extract_hrefs(html, base_url, root_domain):
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"Impossible de parser {base_url} : {e}")
        return set(), set()
    hrefs = set()
    hrefs_no_ext = set()
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
                ):
                    clean_url = full_url.split('#')[0]
                    hrefs.add(clean_url)
                    path = parsed.path
                    filename = path.rstrip('/').split('/')[-1]
                    if (filename and '.' not in filename and filename != '') or (path.endswith('/') and path != '/'):
                        hrefs_no_ext.add(clean_url)
    return hrefs, hrefs_no_ext

def extract_post_params_and_values(html):
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"Impossible de parser dans extract_post_params_and_values : {e}")
        return []
    params = []
    for form in soup.find_all('form'):
        method = form.get('method', '').lower()
        if method == 'post':
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
    return params

def crawl(website, depth_max, root_domain, output_file_brut, output_file_info, cookie=None, crawl_all=False):
    visited = set()
    to_visit = []
    detected_logout_urls = set()
    found_post_params = {}
    all_no_ext_links = set()
    crawl_report = []

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

    while to_visit:
        current_url, depth, method, post_params = to_visit.pop(0)
        current_url_norm = normalize_url(current_url)
        # Ici on filtre les fichiers statiques SANS --all
        if not should_crawl_file(current_url, crawl_all):
            continue
        if (current_url_norm, method) in visited or depth > depth_max:
            continue
        print(f"Crawling ({depth}/{depth_max}): {current_url}")
        visited.add((current_url_norm, method))

        try:
            if method == 'GET':
                resp = session.get(current_url, allow_redirects=True, timeout=10, verify=False)
            elif method == 'POST':
                resp = session.post(current_url, data=post_params, allow_redirects=True, timeout=10, verify=False)
            else:
                continue
        except Exception as e:
            print(f"Erreur sur {current_url}: {e}")
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

        with open(output_file_brut, 'a', encoding='utf-8') as f:
            f.write(f"{current_url}\t{method}\t{status}\t{size}\n")
        with open(output_file_info, 'a', encoding='utf-8') as f:
            f.write(f"URL: {current_url}\nStatus: {status}\nSize: {size}\n\n")

        if resp.headers.get('content-type', '').startswith('text/html'):
            html = resp.text
            hrefs, hrefs_no_ext = extract_hrefs(html, current_url, root_domain)
            all_no_ext_links.update(hrefs_no_ext)
            for h in hrefs:
                h_norm = normalize_url(h)
                if is_logout_url(h) or should_ignore_listing(h):
                    detected_logout_urls.add(h)
                    continue
                if should_crawl_file(h, crawl_all):
                    already_seen = ((h_norm, 'GET') in visited or any(normalize_url(x[0]) == h_norm and x[2] == 'GET' for x in to_visit))
                    if not already_seen:
                        to_visit.append((h, depth+1, 'GET', None))
                    parsed_h = urlparse(h)
                    dir_path = os.path.dirname(parsed_h.path)
                    if dir_path and not dir_path.endswith('/'):
                        dir_path += '/'
                    dir_url = f"{parsed_h.scheme}://{parsed_h.netloc}{dir_path}"
                    dir_url_norm = normalize_url(dir_url)
                    already_seen_dir = ((dir_url_norm, 'GET') in visited or any(normalize_url(x[0]) == dir_url_norm and x[2] == 'GET' for x in to_visit))
                    if dir_path and not already_seen_dir and not should_ignore_listing(dir_url):
                        to_visit.append((dir_url, depth+1, 'GET', None))

            params = extract_post_params_and_values(html)
            if params:
                found_post_params[current_url] = params

    # COMPTE RENDU GLOBAL
    print("\n--- COMPTE RENDU GLOBAL DU CRAWL ---")
    for entry in crawl_report:
        if entry["method"] == "POST":
            pp = entry["post_params"] if entry["post_params"] else ""
            nb_post = len(pp.split("&")) if isinstance(pp, str) and pp else (len(pp) if isinstance(pp, list) else 0)
            print(f'URL: {entry["url"]} | Method: POST | Depth: {entry["depth"]} | POST: {pp} | Nb_POST: {nb_post} | Status: {entry["status"]} | Size: {entry["size"]}')
        elif entry["method"] == "GET":
            if entry["post_params"]:
                nb_get = len(entry["post_params"].split("&")) if isinstance(entry["post_params"], str) else (len(entry["post_params"]) if entry["post_params"] else 0)
                print(f'URL: {entry["url"]} | Method: GET | Depth: {entry["depth"]} | GET: {entry["post_params"]} | Nb_GET: {nb_get} | Status: {entry["status"]} | Size: {entry["size"]}')
            else:
                print(f'URL: {entry["url"]} | Method: GET | Depth: {entry["depth"]} | Status: {entry["status"]} | Size: {entry["size"]}')

    print(f"\nOutput written to: {output_file_brut}, {output_file_info}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--website', required=True, help='URL du site à crawler')
    parser.add_argument('--depth', type=int, default=5, help='Profondeur maximale')
    parser.add_argument('--output', required=True, help='Fichier de sortie (basename, 2 fichiers seront créés)')
    parser.add_argument('--cookie', default=None, help='Cookies à utiliser pour la session')
    parser.add_argument('--all', action='store_true', help='Inclure les fichiers statiques')
    args = parser.parse_args()

    website = args.website.rstrip('/')
    root_domain = urlparse(website).netloc

    tstamp = time.strftime('%Y%m%d_%H%M%S')
    output_file_brut = f"{args.output}/{tstamp}-{root_domain}.txt"
    output_file_info = f"{args.output}/{tstamp}-{root_domain}_info.txt"

    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

    crawl(website, args.depth, root_domain, output_file_brut, output_file_info, args.cookie, args.all)
