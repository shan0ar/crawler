# crawler.py

## Overview

**crawler.py** is a Python 3 web crawler for authenticated session crawling, designed for security auditing, penetration testing, and web reconnaissance.  
It explores websites, enumerates URLs (GET and POST), extracts forms and parameters, and outputs results to files for further analysis.  
It is especially useful for crawling web applications where session cookies are required (such as admin panels), and where you want to avoid triggering logout/disconnect URLs that could break your session.

---

## Features

- **Python 3 compatible**
- **Handles session cookies** (via `--cookie`)
- **Depth-limited crawling** (`--depth`)
- **GET and POST form extraction**
- **Detects and avoids crawling logout/disconnect/exit URLs** (configurable patterns: `logout.php`, `disconnect.php`, `exit.php`, `login.php?logout=1`, etc)
- **Outputs two files:**  
  - `*-<domain>.txt`: List of all discovered URLs, including those with parameters.
  - `*-<domain>_info.txt`: Detailed info with GET/POST parameters, response status, size, and depth.
- **Configurable output directory** (`--output`)
- **Terminal output showing crawling progress and detailed info**
- **All code and output in English**

---

## Installation

Clone the repo and install dependencies:

```bash
git clone https://github.com/shan0ar/crawler.git
cd crawler
pip3 install -r requirements.txt
```

**Requirements:**  
- Python 3.x  
- `requests`  
- `beautifulsoup4`

Or install dependencies manually:

```bash
pip3 install requests beautifulsoup4
```

---

## Usage

### Basic usage

```bash
python3 crawler.py --website "https://targetsite.com" --depth 4
```

### With session cookie (for authenticated crawling)

```bash
python3 crawler.py --website "https://targetsite.com" --depth 4 --cookie "PHPSESSID=xxx;token=yyy"
```

### Specify output directory

```bash
python3 crawler.py --website "https://targetsite.com" --depth 4 --output /path/to/outputdir
```
Output files will be saved in `/path/to/outputdir`.

### Full example

```bash
python3 crawler.py --website "http://192.168.1.10:8080" --depth 5 --cookie "PHPSESSID=abcdef123456" --output /root/Collectes/ProjectX
```

---

## Output

### Terminal

For each URL crawled:
```
Crawling (1/4): https://targetsite.com
Crawling (2/4): https://targetsite.com/dashboard
Crawling (3/4): https://targetsite.com/admin.php
...
```

For each result, detailed info is printed (matches info file):

```
URL: https://targetsite.com/admin.php | Method: GET | Depth: 2 | Status: 200 | Size: 3254
URL: https://targetsite.com/logout.php | Method: GET | Depth: 3 | Status: 200 | Size: 875 (not crawled to avoid breaking the cookie)
...
```

### Files

#### `<date>-<domain>.txt`
List of all unique URLs found:
```
https://targetsite.com
https://targetsite.com/login.php
https://targetsite.com/login.php?error=1
https://targetsite.com/admin.php
https://targetsite.com/logout.php
```
For URLs with GET parameters, the base URL is listed first, and parameterized URLs are listed directly below.

#### `<date>-<domain>_info.txt`
Detailed info for each request:
```
URL: https://targetsite.com/login.php | Method: GET | Depth: 2 | GET: error | Nb_GET: 1 | Status: 200 | Size: 1234
URL: https://targetsite.com/logout.php | Method: GET | Depth: 3 | Status: 200 | Size: 875 (not crawled to avoid breaking the cookie)
...
```

---

## Command-line Arguments

| Argument         | Description                                               | Example                                   |
|------------------|----------------------------------------------------------|-------------------------------------------|
| `--website, -w`  | Target website (required)                                | `--website "https://targetsite.com"`      |
| `--depth, -d`    | Maximum crawl depth (default: 3)                         | `--depth 4`                               |
| `--cookie, -c`   | Session cookie string                                    | `--cookie "PHPSESSID=xxx;token=yyy"`      |
| `--output, -o`   | Output directory for result files                        | `--output /root/Collectes/ProjectX`       |

---

## Session-safe Crawling

The crawler:
- Detects URLs matching logout/disconnect/exit patterns (`logout.php`, `disconnect.php`, `exit.php`, `login.php?logout=1`, etc).
- Skips crawling these URLs to avoid breaking your session/cookie.
- Still records them in output files, with `(not crawled to avoid breaking the cookie)` tag in the info file.

---

## Typical Workflow

1. **Log in to your target application manually.**
2. **Copy your session cookie from your browser** (e.g., using Developer Tools).
3. **Run the crawler with your cookie:**
   ```bash
   python3 crawler.py --website "https://yourtarget.com" --depth 4 --cookie "PHPSESSID=yourvalue"
   ```
4. **Review output files for discovered endpoints and parameters.**

---

## Example: Authenticated Penetration Testing

```bash
python3 crawler.py --website "https://testsite.local" --depth 6 --cookie "PHPSESSID=deadbeef" --output /home/user/collect/testsite
```
You will get:
- `/home/user/collect/testsite/<date>-testsite.local.txt` (all discovered URLs)
- `/home/user/collect/testsite/<date>-testsite.local_info.txt` (detailed crawl info)

---

## Notes

- The crawler only visits URLs on the same domain and subdomains.
- POST forms are submitted with default/static values found in the HTML.
- Crawling too deep or too broad may result in a large number of requests.
- No support for JavaScript execution (static HTML only).
- Only session cookies are supported for authentication (no login automation).

---

## License

MIT License

---

## Author

- [Your Name](https://github.com/shan0ar)

---

## Support

Open a GitHub issue or contact the author for support or feature requests.
