from db_connect import get_db_connection

print("🔌 Testing connection to 'campusfind' database...")
conn = get_db_connection()

if conn:
    print("✅ Connected successfully to campusfind!")
    
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    
    print(f"\n📊 Found {len(tables)} tables:")
    for table in tables:
        print(f"   - {table[0]}")
    
    cursor.close()
    conn.close()
else:
    print("❌ Connection failed!")
    print("\nCheck:")
    print("1. XAMPP MySQL is running (green light)")
    print("2. Database 'campusfind' exists in phpMyAdmin")