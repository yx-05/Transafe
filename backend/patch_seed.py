with open("seeds/seed_db.py", "r") as f:
    lines = f.readlines()
with open("seeds/seed_db.py", "w") as f:
    for line in lines:
        if '"pin_hash": DEMO_PIN_HASH' not in line:
            f.write(line)
