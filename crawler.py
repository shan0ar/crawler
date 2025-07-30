# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import argparse
import datetime
import os

requests.packages.urllib3.disable_warnings()

def parse_cookie_string(cookie_str):
    cookies = {}
    if cookie_str:
        for item in cookie_str.split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                cookies[k.strip()] = v.strip()
    return cookies

def is_allowed_subdomain(netloc, root_domain):
    netloc = netloc.lower()
    root_domain = root_domain.lower()
    return netloc == root_domain or netloc.endswith("." + root_domain)

def extract_hrefs(html, base_url, root_domain):
    soup = BeautifulSoup(html, "html.parser")
    hrefs = set()
    for tag in soup.find_all('a', href=True):
        href = urljoin(base_url, tag['href'])
        parsed_href = urlparse(href)
        if (parsed_href.scheme in ['http', 'https']
            and is_allowed_subdomain(parsed_href.netloc, root_domain)
            and parsed_href.netloc != ""
            and href.split('#')[0] != ""
            and not href.strip() == "https://"):
            hrefs.add(href.split('#')[0])
    return hrefs

def extract_post_forms(html, base_url, root_domain):
    soup = BeautifulSoup(html, "html.parser")
    post_forms = []
    for form in soup.find_all('form'):
        method = form.get('method', '').lower()
        if method == 'post':
            action = form.get('action')
            if not action:
                continue
            post_url = urljoin(base_url, action)
            parsed_post_url = urlparse(post_url)
            if (parsed_post_url.scheme in ['http', 'https']
                and is_allowed_subdomain(parsed_post_url.netloc, root_domain)
                and parsed_post_url.netloc != ""):
                data = {}
                for input_tag in form.find_all('input'):
                    name = input_tag.get('name')
                    value = input_tag.get('value', '')
                    if name: data[name] = value
                for textarea in form.find_all('textarea'):
                    name = textarea.get('name')
                    value = textarea.text
                    if name: data[name] = value
                for select in form.find_all('select'):
                    name = select.get('name')
                    value = ''
                    opt = select.find('option', selected=True)
                    if opt:
                        value = opt.get('value', '')
                    elif select.find('option'):
                        value = select.find('option').get('value','')
                    if name: data[name] = value
                post_forms.append((post_url, data))
    return post_forms

def extract_get_params(url):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return [str(k) for k in qs.keys()]

def extract_post_params_and_values(html):
    soup = BeautifulSoup(html, "html.parser")
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

def format_brut_line(url, get_params):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    params_to_add = [p for p in get_params if p not in qs]
    if get_params and params_to_add:
        sep = '&' if parsed.query else '?'
        return "{}{}{}".format(url, sep, "&".join(["{}=".format(param) for param in params_to_add]))
    else:
        return url

def is_logout_url(url):
    url_lower = url.lower()
    parsed = urlparse(url_lower)
    path = parsed.path
    query = parsed.query
    if (
        path.endswith("logout.php")
        or path.endswith("disconnect.php")
        or path.endswith("exit.php")
        or path.endswith("logout")
        or (path.endswith("login.php") and "logout=1" in query)
    ):
        return True
    if url_lower.endswith("logout") or url_lower.endswith("logout.php") or url_lower.endswith("disconnect.php") or url_lower.endswith("exit.php"):
        return True
    if "login.php?logout=1" in url_lower:
        return True
    return False

def crawl(start_url, max_depth, root_domain, output_file_brut, output_file_info, cookie_str):
    visited = set()
    result = {}
    detected_logout_urls = set()
    url_depths = {}
    to_visit = [(start_url, 1, 'GET', None)]

    session = requests.Session()
    if cookie_str:
        cookies = parse_cookie_string(cookie_str)
        session.cookies.update(cookies)

    while to_visit:
        current_url, depth, method, data = to_visit.pop(0)
        if (current_url, method) in visited or depth > max_depth:
            continue
        visited.add((current_url, method))
        url_depths[(current_url, method)] = depth

        print(f"Crawling ({depth}/{max_depth}): {current_url}")

        try:
            if method == 'GET':
                r = session.get(current_url, verify=False, timeout=10)
            else:
                r = session.post(current_url, data=data, verify=False, timeout=10)
            status_code = r.status_code
            page_size = len(r.content)
            html = r.text
        except Exception:
            status_code = "ERR"
            page_size = 0
            html = ""

        hrefs = extract_hrefs(html, current_url, root_domain)
        for h in hrefs:
            if is_logout_url(h):
                detected_logout_urls.add(h)
                continue
            if (h, 'GET') not in visited and all((h, 'GET') != (x[0], x[2]) for x in to_visit):
                to_visit.append((h, depth+1, 'GET', None))

        post_forms = extract_post_forms(html, current_url, root_domain)
        for post_url, post_data in post_forms:
            if is_logout_url(post_url):
                detected_logout_urls.add(post_url)
                continue
            if (post_url, 'POST') not in visited and all((post_url, 'POST') != (x[0], x[2]) for x in to_visit):
                to_visit.append((post_url, depth+1, 'POST', post_data))

        get_params = extract_get_params(current_url)
        post_params = extract_post_params_and_values(html)

        result[(current_url, method)] = {
            'url': current_url,
            'get': get_params,
            'post': post_params,
            'status': status_code,
            'size': page_size,
            'method': method
        }

    urls_map = {}
    for key in sorted(result.keys()):
        url, method = key
        if method == 'GET':
            parsed = urlparse(url)
            base_url = "{}://{}{}".format(parsed.scheme, parsed.netloc, parsed.path)
            if base_url not in urls_map:
                urls_map[base_url] = []
            urls_map[base_url].append((url, parse_qs(parsed.query)))

    for logout_url in detected_logout_urls:
        parsed = urlparse(logout_url)
        base_url = "{}://{}{}".format(parsed.scheme, parsed.netloc, parsed.path)
        if base_url not in urls_map:
            urls_map[base_url] = []
        urls_map[base_url].append((logout_url, parse_qs(parsed.query)))

    lines = []
    for base_url in sorted(urls_map.keys()):
        already_printed = set()
        lines.append(base_url)
        already_printed.add(base_url)
        for full_url, param_dict in sorted(urls_map[base_url]):
            if full_url != base_url and full_url not in already_printed:
                lines.append(full_url)
                already_printed.add(full_url)

    with open(output_file_brut, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line + "\n")

    with open(output_file_info, 'w', encoding='utf-8') as f:
        for key in sorted(result.keys()):
            url, method = key
            depth = url_depths.get((url, method), "?")
            parts = [f"URL: {url}"]
            parts.append(f"Method: {method}")
            parts.append(f"Depth: {depth}")
            if result[key]['get']:
                parts.append("GET: " + ",".join(result[key]['get']))
                parts.append(f"Nb_GET: {len(result[key]['get'])}")
            if result[key]['post']:
                parts.append("POST: " + ",".join(result[key]['post']))
                parts.append(f"Nb_POST: {len(result[key]['post'])}")
            parts.append(f"Status: {result[key]['status']}")
            parts.append(f"Size: {result[key]['size']}")
            line = " | ".join(parts)
            if is_logout_url(url):
                line += " (not crawled to avoid breaking the cookie)"
            f.write(line + "\n")
            print(line)
        for logout_url in detected_logout_urls:
            if (logout_url, 'GET') not in result and (logout_url, 'POST') not in result:
                line = f"URL: {logout_url}"
                line += " | (not crawled to avoid breaking the cookie)"
                f.write(line + "\n")
                print(line)
    print(f"Output written to: {output_file_brut}, {output_file_info}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--website", "-w", required=True, help="Target website")
    parser.add_argument("--depth", "-d", type=int, default=3, help="Maximum crawl depth")
    parser.add_argument("--cookie", "-c", default="", help="Session cookie (example: PHPSESSID=xxx;token=yyy)")
    parser.add_argument("--output", "-o", default="", help="Output directory for files")
    args = parser.parse_args()

    dt = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    root_domain = urlparse(args.website).netloc

    output_dir = args.output.strip()
    if output_dir:
        if not os.path.isdir(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                print("Error creating output directory:", e)
                exit(1)
        output_file_brut = os.path.join(output_dir, f"{dt}-{root_domain}.txt")
        output_file_info = os.path.join(output_dir, f"{dt}-{root_domain}_info.txt")
    else:
        output_file_brut = f"{dt}-{root_domain}.txt"
        output_file_info = f"{dt}-{root_domain}_info.txt"

    crawl(args.website, args.depth, root_domain, output_file_brut, output_file_info, args.cookie)
