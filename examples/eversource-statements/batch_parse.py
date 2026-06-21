import sys, email, json
sys.path.insert(0, "/tmp")
from parse_stmt import parse_front, parse_net, pdftext

raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
rows = []
for ch in raw.split("=====STMT_BOUNDARY====="):
    ch = ch.strip("\n")
    if not ch.strip():
        continue
    nl = ch.find("\n")
    subj, src = ch[:nl].strip(), ch[nl + 1:]
    try:
        msg = email.message_from_string(src)
    except Exception as e:
        print("MSG ERR", subj, e, file=sys.stderr); continue
    texts = []
    i = 0
    for part in msg.walk():
        fn = (part.get_filename() or "")
        if fn.lower().endswith(".pdf"):
            data = part.get_payload(decode=True)
            if not data:
                continue
            p = f"/tmp/_p{i}.pdf"; open(p, "wb").write(data); i += 1
            texts.append(pdftext(p))
    if not texts:
        print("NO PDFS:", subj, file=sys.stderr); continue
    combined = "\n".join(texts)
    r = {"subject": subj}
    r.update(parse_front(combined))
    r.update(parse_net(combined))
    rows.append(r)

with open(sys.argv[2], "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")
print(f"parsed {len(rows)} statements", file=sys.stderr)
