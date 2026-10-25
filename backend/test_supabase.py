from supabase import create_client, Client

# Paste your copied values from the Supabase dashboard here
SUPABASE_URL = "https://pyuupxyjvppkklymnfxx.supabase.co"
SUPABASE_KEY = "sb_publishable_weanlz_NF1LAy2G6goaOvg_W5Ic3eGn"  # Replace with your full Publishable key

# Initialize client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def test_connection():
    try:
        # Query the equipment table
        response = supabase.table("equipment").select("*").execute()
        print("Connected to Supabase successfully!")
        print("Equipment table records:", response.data)
    except Exception as e:
        print("Connection failed:", e)

if __name__ == "__main__":
    test_connection()