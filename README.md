# 🎾 Tennis Court Notifier (LINE Messaging API)

ระบบตรวจสอบตารางคอร์ทเทนนิสอัตโนมัติสำหรับช่วงเวลา **18.00–21.00 น.** (เช็กล่วงหน้า **วันนี้ + วันพรุ่งนี้**) จาก 5 สนาม:
1. **Cozy Tennis** (`https://book.cozytennis.com/schedule`) — LINE OA `@cozytennis`
2. **Ozzy Court / The Challenge Tennis Club** (`https://court.ozzy.asia/court-demo`) — LINE OA `@925atqia`
3. **Simoorgh Tennis Academy (Bangna)** (`https://getoncourt.app/en/courts/simoorgh-tennis-academy-bangna/book`) — LINE OA `@409mkpcj` *(ใช้ `ONCOURT_EMAIL` / `ONCOURT_PASSWORD` ใน Secrets)*
4. **ศูนย์กีฬาสวนหลวง ร.9 (เฉพาะ Tennis ไม่รวม Tennis Board)** (`https://www.courtthai.com/v/suanluang9/booking?sport=TENNIS`) — LINE OA `@slr9sportcenter` *(เปิดถึง 20:00 น.)*
5. **BEAT Discovery (เฉพาะ Tennis มาตรฐาน ไม่รวมคอร์ท Kid)** (`https://beatdiscovery.okrabook.com/venues/v2/venue/BEAT%20Discovery`) — LINE OA `@BEATDiscovery` *(ใช้ Scheduled Automation บนเครื่อง เนื่องจากติด Cloudflare anti-bot challenge บน GitHub Actions)*

รันอัตโนมัติบน **GitHub Actions** ทุกๆ 15 นาที (ช่วงเวลา **09.00–19.00 น.** เวลาไทย) และส่งข้อความแจ้งเตือนเข้า **LINE** ทันทีเมื่อมีคอร์ทว่างใหม่ (แยกให้ชัดเจนทั้งกรณีว่างติดกันและว่างแยก 1 ชม.) พร้อมระบบจำสถานะเพื่อไม่ให้แจ้งเตือนซ้ำ

---

## ✨ ความสามารถหลัก
- ตรวจสอบช่วงเวลา **18.00–19.00 น.**, **19.00–20.00 น.** และ **20.00–21.00 น.** ของ **วันนี้และวันพรุ่งนี้** (`Asia/Bangkok`)
- แยกแสดงผลชัดเจนในรูปแบบ LINE Flex Message พร้อมปุ่มกดจองเข้าแชท LINE OA ของสนามพร้อมข้อความอัตโนมัติ (`@cozytennis`, `@925atqia`):
  - `🔥 ว่างติดกัน 3 ชม. (18:00–21:00)` หรือ `2 ชม.` เมื่อคอร์ทเดียวกันว่างต่อเนื่อง
  - `⏱️ ว่าง 1 ชม. (18:00–19:00)` / `(19:00–20:00)` / `(20:00–21:00)` เมื่อว่างแยกชั่วโมง
  - ติดป้าย `🆕` หน้าคอร์ทที่เพิ่งหลุดจองใหม่ในรอบนั้น
- เก็บสถานะใน `state.json` ผ่าน `actions/cache` บน GitHub Actions เพื่อแจ้งเตือนเฉพาะเมื่อมีช่องว่างใหม่ (ประหยัดโควตาข้อความ LINE)
- ข้ามชั่วโมงของวันนี้ที่เลยเวลาไปแล้วโดยอัตโนมัติ (`SKIP_PAST_HOURS=true`)

---

## 🛠️ ขั้นตอนการตั้งค่า LINE Messaging API (ทำครั้งเดียว)

> หมายเหตุ: ใช้ **LINE Messaging API** ผ่าน LINE Official Account (ฟรี 300 ข้อความ/เดือน สำหรับบัญชีไทย)

1. ไปที่ [LINE Developers Console](https://developers.line.biz/console/) แล้ว Login ด้วยบัญชี LINE ของคุณ
2. กด **Create a new provider** (ตั้งชื่ออะไรก็ได้ เช่น `Court Alerts`)
3. กด **Create a Messaging API channel** กรอกชื่อบอท (เช่น `Tennis Court Alert`) และรายละเอียดให้ครบ
4. เข้าไปที่แท็บ **Messaging API** ของ Channel ที่สร้าง:
   - สแกน QR Code เพื่อ **เพิ่มบอทเป็นเพื่อน** ในแอป LINE บนมือถือ
   - เลื่อนลงด้านล่างสุด หาหัวข้อ **Your user ID** (ขึ้นต้นด้วย `U...`) แล้วคัดลอกเก็บไว้ใช้เป็น `LINE_USER_ID`
   - เลื่อนหาหัวข้อ **Channel access token (long-lived)** กดปุ่ม **Issue** แล้วคัดลอก Token เก็บไว้ใช้เป็น `LINE_CHANNEL_ACCESS_TOKEN`
5. *(แนะนำ)* ในแท็บ Messaging API ปิด **Auto-reply messages** เพื่อให้บอทไม่ตอบข้อความอัตโนมัติเวลาเราพิมพ์

---

## 🔐 วิธีใส่ Secrets บน GitHub เพื่อให้ระบบเริ่มแจ้งเตือน

1. เปิด Repository นี้บน GitHub แล้วไปที่แท็บ **Settings** > **Secrets and variables** > **Actions**
2. กด **New repository secret** เพิ่มค่าที่จำเป็น:
   - `LINE_CHANNEL_ACCESS_TOKEN`: ค่า Channel access token ที่ได้จากข้อ 4
   - `LINE_USER_ID`: ค่า User ID (`U...`) ของคุณ
   - *(สำหรับสนาม Simoorgh / OnCourt)* เพิ่ม `ONCOURT_EMAIL` และ `ONCOURT_PASSWORD` ของบัญชี OnCourt (หากยังไม่ได้ตั้งรหัสผ่านให้ใช้บัญชีแบบ Email/Password ของ OnCourt เพื่อหลีกเลี่ยงระบบติด 2FA ของ Google)
3. ไปที่แท็บ **Actions** > เลือก Workflow **Check Tennis Courts**
   - กด **Run workflow** แล้วติ๊ก **`force_notify = true`** เพื่อทดสอบรับข้อความแจ้งเตือนเข้า LINE ทันที

---

## 💻 การทดสอบรันบนเครื่องตัวเอง (Local)

```bash
pip install -r requirements.txt
python -m playwright install chromium

# ทดสอบเช็กเว็บโดยไม่ส่ง LINE และไม่บันทึก state.json
python -m src.main --dry-run

# รัน Unit tests
python -m unittest discover -s tests -v
```

หากต้องการทดสอบส่งเข้า LINE จากเครื่องตัวเอง ให้คัดลอก `.env.example` เป็น `.env` แล้วใส่ Token และ User ID จากนั้นรัน:

```bash
python -m src.main --force-notify
```

---

## ⚙️ การปรับแต่งค่า (Environment Variables)

| ตัวแปร | ค่าเริ่มต้น | คำอธิบาย |
| :--- | :--- | :--- |
| `DAYS_AHEAD` | `2` | จำนวนวันล่วงหน้า (`2` = วันนี้ + พรุ่งนี้) |
| `TARGET_HOURS` | `18,19,20` | ชั่วโมงเริ่มต้นที่ต้องการเช็ก (`18` = 18:00–19:00, `19` = 19:00–20:00, `20` = 20:00–21:00) |
| `SKIP_PAST_HOURS` | `true` | ข้ามชั่วโมงของวันนี้ที่เลยเวลาปัจจุบันไปแล้ว |
| `BEAT_EXCLUDE_KID_COURTS` | `true` | กรองคอร์ทเด็ก `(Kid)` ของ BEAT Discovery ออก |
| `STATE_FILE` | `state.json` | ไฟล์เก็บสถานะคอร์ทที่แจ้งเตือนไปแล้ว |
