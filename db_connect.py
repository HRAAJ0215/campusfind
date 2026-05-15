import mysql.connector
from mysql.connector import Error

def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password='',
            database='campusfind'
        )
        return connection
    except Error as e:
        print(f"Database connection error: {e}")
        return None