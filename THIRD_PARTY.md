# 포함된 외부 소프트웨어와 자료

SRT-ARA의 **도구 코드는 MIT 라이선스**다(`LICENSE`). 아래 파일은 도구 코드가 아니라 함께 넣은 외부 소프트웨어·자료이며, **MIT가 아니라 각자의 조건**을 따른다. 배포할 때 이 파일들과 이 문서, `licenses/` 폴더를 함께 넣는다. 이 파일들은 따로 설치하지 않으며, 폐쇄망에도 도구 폴더째 옮기면 된다.

| 이름 | 버전 | 파일 | 크기 | 용도 | 라이선스 | 받은 곳 |
| --- | --- | --- | --- | --- | --- | --- |
| Mermaid | 12.1.0 | `srtgen/web/vendor/mermaid.min.js` | 5,493,176 바이트 | 확인·편집 화면에서 다이어그램을 그림으로 바꿈 | MIT | https://cdn.jsdelivr.net/npm/mermaid@12.1.0/dist/mermaid.min.js |
| CWE 목록 (일부) | 페이지 갱신일 2026.04.30 | `srtgen/data/cwe_views.json` | 16,505 바이트 | CWE-658(C)·659(C++)·660(Java)에 든 약점의 번호와 이름 (103·97·84개). 취약점 이름 채우기, 화면 선택지, 요약의 분류 | CWE Terms of Use | https://cwe.mitre.org/data/definitions/658.html (659.html·660.html도 같다. 내려받은 것은 같은 사이트의 `data/csv/<번호>.csv.zip`) |
| .NET 코드 분석 품질 규칙 목록 (일부) | 문서 날짜 2024.01.31 | `srtgen/data/dotnet_quality_rules.json` | 21,292 바이트 | 규칙 번호와 제목 335개(CA, 같은 표의 IL 포함). ".NET Framework Design Guidelines" 기준의 규칙명 채우기, 화면 선택지 | CC BY 4.0 | https://raw.githubusercontent.com/dotnet/docs/main/docs/fundamentals/code-analysis/quality-rules/index.md (96,334 바이트, Microsoft Learn의 quality-rules 페이지 원본) |
| .NET 코드 스타일 규칙 목록 (일부) | 문서 날짜 2026.07.09 | `srtgen/data/csharp_style_rules.json` | 6,717 바이트 | 규칙 번호와 제목 130개(IDE). "C# Coding Conventions" 기준의 규칙명 채우기, 화면 선택지 | CC BY 4.0 | https://raw.githubusercontent.com/dotnet/docs/main/docs/fundamentals/code-analysis/style-rules/index.md (25,067 바이트, Microsoft Learn의 style-rules 페이지 원본) |

보안약점 점검 목록(44개)은 파일이 아니라 `srtgen/criteria.py` 안에 있다. 「무기체계 소프트웨어 개발 및 관리 매뉴얼」, 방위사업청 매뉴얼 제2024-6호(개정 : 2024. 12.26.) 부록 7 제2장 '3. 시험기준'의 보안약점 점검 목록(부록 7-10~11쪽)에서 CWE 번호와 이름을 옮긴 것이다.


## 받은 경위

Mermaid는 2026.10.14에 개발 PC의 다른 프로젝트에 넣어 두었던 파일(위 주소에서 받은 날 2026.10.13)을 그대로 복사했다. 인터넷에서 새로 받지 않았고, 원래 파일과 검증값(아래)이 같은 것을 확인했다.

CWE 목록은 2026.10.14에 위 주소에서 받아, **번호와 이름(제목)만** 뽑아 넣었다. 설명·예제 등 본문은 넣지 않았다. MISRA C/C++의 규칙 글은 구매해야 하는 문서(https://misra.org.uk/publications/, PDF는 1인 사용 허락)에 있고 공개된 규칙명 목록이 없으므로 넣지 않았다. MISRA의 규칙 번호와 규칙명은 작성자가 가진 문서를 보고 직접 적는다.

.NET 코드 분석 품질 규칙 목록과 코드 스타일 규칙 목록은 2026.10.14에 dotnet/docs 저장소의 원본(위 표)과 LICENSE(18,649 바이트)를 받아, **번호와 제목만** 뽑아 넣었다(범위로 묶인 줄 CA1865-CA1867은 번호마다 한 줄씩 나눴다). 설명은 넣지 않았다. Microsoft 문서가 설계 규칙은 .NET Framework Design Guidelines를 따른다고 밝히므로(https://learn.microsoft.com/dotnet/fundamentals/code-analysis/quality-rules/design-warnings) 이 목록 전체(CA·IL)를 그 기준의 목록으로 쓴다(설계 규칙 밖의 규칙까지 이 기준에 넣은 것은 이 도구가 정한 것이다).

## 함께 넣지 않지만 쓰는 것

- **Python**(PSF-2.0): 실행 환경. 사용자 PC에 설치된 것을 쓴다(폐쇄망용 묶음에는 아래처럼 함께 들어 있다).
- **Pillow·Pygments**: `--code image`(코드를 그림으로)에서만 쓰고, Pillow가 없으면 글자 발췌로 만든다(Pygments는 구문 강조에만 쓴다). 소스 저장소에는 넣지 않는다.

## 폐쇄망용 묶음에만 들어가는 것

소스 저장소에는 넣지 않고, 별도 zip(`SRT-ARA_ver<버전>_offline.zip`, GitHub Release의 첨부 파일)에만 들어간다. 폐쇄망 PC에서 설치 없이 쓰도록 휴대용 Python을 도구 폴더의 `python/`에 풀고 Pillow·Pygments를
미리 넣은 것이다. 세 파일 모두 재배포가 허락되며, 고지는 묶음 안에 그대로 있다.

| 이름 | 버전 | 받은 파일 (크기) | 묶음 안의 위치 | 라이선스와 고지 | 받은 곳 |
| --- | --- | --- | --- | --- | --- |
| Python (Windows 64비트, 설치 관리자용 전체 판) | 3.14.8 | `python-3.14.8-amd64.zip` (32,879,974 바이트) | `python/` (설명서 `Doc`, 빌드용 `include`·`libs`는 뺌) | PSF-2.0. 안에 든 OpenSSL(Apache-2.0)·Tcl/Tk·SQLite·zlib-ng·libffi·expat·bzip2·xz·mpdecimal·zstd·HACL\* 등의 고지는 `python/LICENSE.txt`, pip와 pip에 든 패키지의 고지는 `python/Lib/site-packages/pip-*.dist-info/licenses/` | https://www.python.org/ftp/python/3.14.8/python-3.14.8-amd64.zip |
| Pillow | 12.3.0 | `pillow-12.3.0-cp314-cp314-win_amd64.whl` (7,237,707 바이트) | `python/Lib/site-packages/PIL/` | MIT-CMU. 안에 든 FreeType(FTL 선택)·libjpeg-turbo·libpng·zlib·XZ(liblzma) 등의 고지는 `python/Lib/site-packages/pillow-12.3.0.dist-info/licenses/LICENSE` | https://pypi.org/project/pillow/12.3.0/ |
| Pygments | 2.21.0 | `pygments-2.21.0-py3-none-any.whl` (1,250,147 바이트) | `python/Lib/site-packages/pygments/` | BSD-2-Clause. `python/Lib/site-packages/pygments-2.21.0.dist-info/licenses/` | https://pypi.org/project/Pygments/2.21.0/ |

2026.10.15에 위 주소에서 받았고, SHA-256이 공개값(Python은 python.org의 `ftp/python/index-windows.json`,
나머지는 PyPI)과 같은 것을 확인했다. Pillow 고지에 나오는 GPL 글은 FreeType의 이중 라이선스(FTL을 따름) 안내와 XZ의 명령줄
도구(묶음에 없음)에 관한 것이라 묶음에는 적용되지 않는다. 이 묶음의 Python(64비트)은 Windows 10 이상 64비트에서 돈다.

## 파일 검증값 (SHA-256)

```
6484afc32872a3aa16cac9a76ba1816a1ed4cc870a6593cc2e17757750f518b2  srtgen/web/vendor/mermaid.min.js
b62f6f481d259ae59c35166b12fc14b122e7278e13a0cd2105ba93dd2a2968fe  srtgen/data/cwe_views.json
cbe2e3e91c63d7f307b011ec8db71e4933f4ef43dead13814cc0b8fc91b93958  srtgen/data/dotnet_quality_rules.json
1373b463170d5977f2ca530efe337a3446853d2dc6173bf8fddc6ebd877d8c6d  srtgen/data/csharp_style_rules.json
```

데이터 파일은 받은 원본에서 이 도구가 만든 것이라, 원본이 갱신되어 다시 만들면 값이 달라진다.

폐쇄망용 묶음에 넣으려고 받은 파일(위 표)의 검증값이다. 묶음을 만들 때 이 값과 대조한다:

```
4873947a8afc037846b180312b83c744a4146a851cfd316a75c3125a4d8299da  python-3.14.8-amd64.zip
fdafc9cce40277e0f7a0feabce0ee50dd2fa1800f3b38015e51296b5e814048d  pillow-12.3.0-cp314-cp314-win_amd64.whl
2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9  pygments-2.21.0-py3-none-any.whl
```

## 라이선스 전문

- `LICENSE` — SRT-ARA 도구 코드의 MIT 라이선스
- `licenses/mermaid-LICENSE.txt` — Mermaid 패키지(npm)에 든 LICENSE 파일
- `licenses/cwe-TERMS.txt` — CWE Terms of Use와 MITRE의 저작권 표시 (https://cwe.mitre.org/about/termsofuse.html)
- `licenses/dotnet-docs-LICENSE.txt` — dotnet/docs 저장소의 LICENSE 파일, Creative Commons Attribution 4.0 International (https://github.com/dotnet/docs/blob/main/LICENSE). .NET 품질 규칙과 코드 스타일 규칙 두 목록에 함께 적용된다

## 주의할 점

- **Mermaid 파일에는 여러 라이브러리가 묶여 있다.** d3, dagre, DOMPurify, KaTeX 등이며 파일 끝의 주석에 각 고지가 들어 있다. 이 파일을 고치거나 줄이지 않고 그대로 배포한다.
- **CWE는 사본에 MITRE의 저작권 표시와 이용 조건을 함께 두어야 한다.** `srtgen/data/cwe_views.json` 안의 저작권 표시와 `licenses/cwe-TERMS.txt`를 지우지 않는다. CWE는 The MITRE Corporation의 상표다.
- **.NET 규칙 목록은 CC BY 4.0이라 출처 표시를 지켜야 한다.** 두 데이터 파일 안의 출처·저작권·라이선스 표시와 `licenses/dotnet-docs-LICENSE.txt`를 지우지 않는다. 원본에서 번호와 제목만 뽑았다는 것(변경 사항)도 그 파일과 이 문서에 적혀 있다.
- **데이터 파일이 없어도 나머지 기능은 그대로 동작한다.** 목록이 없으면 이름을 직접 적거나 화면의 "규칙 목록"에 CSV·TXT로 불러오면 된다.
- **Mermaid 파일이 없어도 나머지 기능은 그대로 동작한다.** 수집, md·hwpx 생성, 편집, 그림 파일 추가는 표준 라이브러리만 쓴다. 파일을 빼면 화면의 "다이어그램 추가"만 쓸 수 없다.
- Mermaid로 만든 그림은 PNG 파일로 소스 옆(`srt_attach/`)에 저장되므로, 보고서를 만들 때는 Mermaid가 필요 없다.
