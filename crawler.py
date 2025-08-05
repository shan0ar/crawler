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
        if url.lower().split('?',1)[0].endswith(ext):
            return False
    return True

def extract_hrefs_and_forms(html, base_url, root_domain):
    """
    Extracts hrefs (GET) and forms (POST) for crawling,
    and for displaying expected POST parameters.
    Returns:
        - hrefs: set of URLs to crawl (for GET)
        - hrefs_no_ext: set of URLs without extension (for directories)
        - forms_found: list of dict {'url':..., 'params':...} for each POST form found
    """
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

    # Extract POST forms (action + expected params)
    for form in soup.find_all('form'):
        method = form.get('method', '').lower()
        action = form.get('action', '')
        form_url = urljoin(base_url, action) if action else base_url
        if (
            method == 'post'
            and urlparse(form_url).scheme in ["http", "https"]
            and is_allowed_subdomain(urlparse(form_url).netloc, root_domain)
            and not should_ignore_listing(form_url)
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
                'params': params
            })

    return hrefs, hrefs_no_ext, forms_found

def get_expected_method_and_params(url, found_forms):
    """
    For a given url, check if there is a POST form matching this url.
    If so, returns ("POST", params), otherwise ("GET", params) if GET params exist, otherwise ("GET", None)
    """
    for form in found_forms:
        if normalize_url(form['url']) == normalize_url(url):
            return "POST", form['params']
    # If GET params exist in URL
    if '?' in url:
        params = []
        query = urlparse(url).query
        for k, v in parse_qsl(query):
            if v:
                params.append(f"{k}={v}")
            else:
                params.append(k)
        return "GET", params if params else None
    return "GET", None

def crawl(website, depth_max, root_domain, output_file_brut, output_file_info, cookie=None, crawl_all=False):
    visited = set()
    to_visit = []
    detected_logout_urls = set()
    all_no_ext_links = set()
    crawl_report = []
    found_forms = []

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

    # This will collect all forms found in the crawl, for reporting expected methods
    all_found_forms = []

    while to_visit:
        current_url, depth, method, post_params = to_visit.pop(0)
        current_url_norm = normalize_url(current_url)
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

        with open(output_file_brut, 'a', encoding='utf-8') as f:
            f.write(f"{current_url}\t{method}\t{status}\t{size}\n")
        with open(output_file_info, 'a', encoding='utf-8') as f:
            f.write(f"URL: {current_url}\nStatus: {status}\nSize: {size}\n\n")

        if resp.headers.get('content-type', '').startswith('text/html'):
            html = resp.text
            hrefs, hrefs_no_ext, forms_found = extract_hrefs_and_forms(html, current_url, root_domain)
            all_no_ext_links.update(hrefs_no_ext)
            all_found_forms.extend([dict(f, depth=depth) for f in forms_found])  # Keep track of all forms for report

            # Standard GET crawling
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

            # Store found POST forms (displayed later)
            for form in forms_found:
                found_forms.append({
                    "url": form['url'],
                    "params": form['params'],
                    "depth": depth
                })

    # GLOBAL CRAWL REPORT
    print("\n--- GLOBAL CRAWL REPORT ---")
    for entry in crawl_report:
        expected_method, params = get_expected_method_and_params(entry["url"], all_found_forms)
        out = f'URL: {entry["url"]} | Method: {entry["method"]} | Depth: {entry["depth"]}'

        if expected_method == "POST" and params:
            out += f' | POST: {",".join(params)} | Nb_POST: {len(params)}'
        elif expected_method == "GET" and params:
            out += f' | GET: {",".join(params)} | Nb_GET: {len(params)}'

        out += f' | Status: {entry["status"]} | Size: {entry["size"]}'
        print(out)

    # Display found POST forms (action + expected params)
    print("\n--- FOUND POST FORMS ---")
    # Remove duplicates for display
    already_seen_forms = set()
    for form in all_found_forms:
        key = (normalize_url(form['url']), ','.join(form['params']) if form['params'] else '', form['depth'])
        if key in already_seen_forms:
            continue
        already_seen_forms.add(key)
        params_str = ', '.join(form['params']) if form['params'] else '(no parameters)'
        print(f"Found POST form URL: {form['url']} | Expected parameters: {params_str} | Depth: {form['depth']}")

    print(f"\nOutput written to: {output_file_brut}, {output_file_info}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--website', required=True, help='URL of the site to crawl')
    parser.add_argument('--depth', type=int, default=5, help='Maximum depth')
    parser.add_argument('--output', required=True, help='Output file (basename, 2 files will be created)')
    parser.add_argument('--cookie', default=None, help='Cookies to use for the session')
    parser.add_argument('--all', action='store_true', help='Include static files')
    args = parser.parse_args()

    website = args.website.rstrip('/')
    root_domain = urlparse(website).netloc

    tstamp = time.strftime('%Y%m%d_%H%M%S')
    output_file_brut = f"{args.output}/{tstamp}-{root_domain}.txt"
    output_file_info = f"{args.output}/{tstamp}-{root_domain}_info.txt"

    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

    crawl(website, args.depth, root_domain, output_file_brut, output_file_info, args.cookie, args.all)
