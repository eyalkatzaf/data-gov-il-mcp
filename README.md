# data_gov_il_mcp

**MCP Server לחיבור data.gov.il לקלוד**

חיבור קבוע בין מאגרי הנתונים הפתוחים של ממשלת ישראל ([data.gov.il](https://data.gov.il)) לבין Claude. אחרי שתפעיל את החיבור, תוכל לשאול את קלוד שאלות כמו "כמה צעירים בני 18-35 גרים בחיפה?" או "מצא לי מאגרים על תחבורה" בכל צ'אט — והוא יביא את התשובה ישירות מ-CKAN של ממשלת ישראל.

---

## מה הכלים שה-Server חושף לקלוד

| כלי | מה הוא עושה |
|------|-------------|
| `datagov_il_search_datasets` | מחפש מאגרים בקטלוג של data.gov.il (תומך עברית ואנגלית) |
| `datagov_il_get_resource_schema` | מחזיר את שמות העמודות של משאב ספציפי + רשומה לדוגמה |
| `datagov_il_query_resource` | שולף רשומות ממשאב עם פילטרים, מיון וחיפוש |
| `datagov_il_youth_by_settlement` | קיצור דרך למשאב הספציפי — תושבים צעירים (18-35) לפי יישוב |

---

## איך מחברים לקלוד — 3 שלבים

### שלב 1 — לקחת את הקוד ל-GitHub

```bash
# צור ריפו ריק חדש ב-GitHub (פרטי או ציבורי, לא משנה)
# ואז מהמחשב שלך:

cd /path/to/data_gov_il_mcp
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/data-gov-il-mcp.git
git push -u origin main
```

### שלב 2 — לפרוס על Render (חינם)

Render הוא הפלטפורמה הכי פשוטה לפריסת MCP Server:

1. היכנס ל-[render.com](https://render.com) והירשם (אפשר עם GitHub)
2. לחץ **New +** → **Web Service**
3. בחר את הריפו `data-gov-il-mcp`
4. Render יזהה אוטומטית את `render.yaml` ויקבע את הכל
5. לחץ **Create Web Service** ותחכה ~2-3 דקות

תקבל URL כזה: `https://data-gov-il-mcp-xxxx.onrender.com`

> **חלופות לפריסה:** Railway.app, Fly.io, או כל ספק שתומך ב-Docker. ה-Dockerfile כלול בריפו.

### שלב 3 — לחבר ל-Claude

#### בקלוד.ai (Web/Mobile):

1. כנס ל-**Settings** → **Connectors** (או **Integrations**)
2. לחץ **Add custom connector**
3. **URL**: הדבק `https://data-gov-il-mcp-xxxx.onrender.com/mcp` _(שים לב ל-`/mcp` בסוף)_
4. **שם**: `Data.gov.il`
5. **Authentication**: None
6. שמור

#### ב-Claude Desktop:

ערוך את `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) או `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "data_gov_il": {
      "command": "python",
      "args": ["/full/path/to/data_gov_il_mcp/server.py"],
      "env": {"MCP_TRANSPORT": "stdio"}
    }
  }
}
```

הפעל מחדש את האפליקציה.

---

## בדיקה מקומית לפני פריסה

```bash
# התקן תלויות
pip install -r requirements.txt

# הרץ ב-stdio (לבדיקה עם MCP Inspector)
MCP_TRANSPORT=stdio python server.py

# או הרץ ב-HTTP (כמו בפרודקשן)
python server.py
# → MCP זמין ב-http://localhost:8000/mcp

# בדיקה עם MCP Inspector
npx @modelcontextprotocol/inspector python server.py
```

---

## דוגמאות לשאלות שתוכל לשאול את קלוד אחרי החיבור

> "כמה תושבים צעירים בני 18-35 יש בכל אחת מ-10 הערים הגדולות בישראל?"

> "תמצא לי מאגרים על תחבורה ציבורית ב-data.gov.il"

> "תוציא לי את רשימת היישובים עם הכי הרבה צעירים, ממוין מהגדול לקטן"

> "מה הסכמה של המשאב הזה: b8112650-a2f8-41f2-9c05-a9b9483fb4c0"

קלוד יקרא לכלים אוטומטית, יביא את הנתונים, ויענה בעברית.

---

## ארכיטקטורה

```
Claude.ai
    ↓ HTTPS / Streamable HTTP
[Your Render Server]:8000/mcp
    ↓ HTTPS
data.gov.il/api/3/action/*
```

ה-MCP Server שלך משמש כ-proxy בין קלוד ל-CKAN של ממשלת ישראל. אין צורך בהזדהות מול data.gov.il (זה API ציבורי).

---

## הערה על אבטחה

ה-Server שלך פתוח לכל מי שיש לו את ה-URL. ל-API ציבורי כמו data.gov.il זה לא מסוכן, אבל אם תרצה הגנה נוספת, תוכל להוסיף API Key פשוט:

ב-`server.py` בתוך `_ckan_request`, הוסף בתחילת כל כלי:

```python
expected_key = os.getenv("MCP_API_KEY")
if expected_key and request.headers.get("X-API-Key") != expected_key:
    raise RuntimeError("Unauthorized")
```

ובחיבור ל-Claude, הוסף Header `X-API-Key` עם הערך.

---

## רישוי וקרדיטים

- הקוד תחת MIT.
- הנתונים בבעלות ממשלת ישראל / הלמ"ס, תחת רישיון Open Data של data.gov.il.
- בנוי על MCP Python SDK (FastMCP) ועל httpx.
