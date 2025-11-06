import sqlite3
import pandas as pd
import os
from datetime import datetime
import requests
from io import BytesIO


class UserDB:
    def __init__(self, db_path=None):
        # ✅ Define database path automatically
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            db_dir = os.path.join(base_dir, "instance")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "users.db")

        self.db_path = db_path
        print(f"📁 Database path: {self.db_path}")

        # ✅ Initialize database if not present
        if not os.path.exists(self.db_path):
            print("🆕 Database not found — creating new one...")
            self.init_database()
            self.import_from_excel()
        else:
            print("✅ Database already exists.")
            if self.is_database_empty():
                print("🔄 Database is empty — importing from Excel...")
                self.import_from_excel()

    def is_database_empty(self):
        """Check if database is empty"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM users')
        count = cursor.fetchone()[0]
        conn.close()

        return count == 0


    def get_connection(self):
        """Get database connection with timeout for concurrent access"""
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_database(self):
        """Initialize SQLite database and create tables - UPDATED SCHEMA"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                member_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                date_of_birth DATE,
                address TEXT,
                blood_group TEXT,
                phone TEXT,
                image_path TEXT,
                membership_type TEXT DEFAULT 'annually',
                membership_joining_date DATE,
                membership_renewal_date DATE,
                password TEXT DEFAULT '123456',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success BOOLEAN,
                FOREIGN KEY (member_id) REFERENCES users (member_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            INSERT OR IGNORE INTO admin_users (username, password) 
            VALUES (?, ?)
        ''', ('admin', 'admin123'))

        conn.commit()
        conn.close()
        print("✅ Database initialized successfully with new schema")

    def import_from_excel(self, file_path):
        """Import user data from Excel file - UPDATED FOR NEW FORMAT"""
        try:
            if not os.path.exists(file_path):
                print(f"❌ Excel file '{file_path}' not found!")
                return False

            df = pd.read_excel(file_path)
            conn = self.get_connection()

            imported_count = 0
            for _, row in df.iterrows():
                try:
                    # Convert date properly
                    date_of_birth = row.get('date of Bitrth') or row.get('date_of_birth')
                    if pd.notna(date_of_birth):
                        if isinstance(date_of_birth, str):
                            date_of_birth = date_of_birth.split()[0]  # Take only date part
                        else:
                            date_of_birth = date_of_birth.strftime('%Y-%m-%d')
                    else:
                        date_of_birth = ''

                    # Set membership type and dates
                    membership_type = 'lifetime'  # Default based on your requirement
                    joining_date = datetime.now().strftime('%Y-%m-%d')

                    # For lifetime membership, renewal date is far future
                    if membership_type == 'lifetime':
                        renewal_date = '2099-12-31'
                    else:
                        renewal_date = (datetime.now().replace(year=datetime.now().year + 1)).strftime('%Y-%m-%d')

                    # CHANGE: INSERT OR IGNORE instead of INSERT OR REPLACE
                    conn.execute('''
                        INSERT OR IGNORE INTO users 
                        (member_id, name, date_of_birth, address, blood_group, phone, image_path,
                         membership_type, membership_joining_date, membership_renewal_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(row['Member Id']),
                        row['Name'],
                        date_of_birth,
                        row.get('Address', ''),
                        row.get('Blood Group', ''),
                        row.get('WhatsApp Number', ''),
                        row.get('Image Path', ''),
                        membership_type,
                        joining_date,
                        renewal_date
                    ))
                    imported_count += 1
                except Exception as e:
                    print(f"❌ Error importing user {row.get('Member Id', 'Unknown')}: {e}")

            conn.commit()
            conn.close()
            print(f"✅ Imported {imported_count} users from Excel")
            return True

        except Exception as e:
            print(f"❌ Error importing from Excel: {e}")
            return False

    def get_user_by_id(self, member_id):
        """Get user data by member_id - FIXED VERSION"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT member_id, name, date_of_birth, address, blood_group, phone, image_path,
                   membership_type, membership_joining_date, membership_renewal_date, created_at
            FROM users WHERE member_id = ?
        ''', (member_id,))

        user = cursor.fetchone()
        conn.close()

        if user:
            return dict(user)
        return None

    def verify_password(self, member_id, password):
        """Verify user password"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT password FROM users WHERE member_id = ?
            ''', (member_id,))

            result = cursor.fetchone()
            conn.close()

            if result:
                if result[0] == password:
                    self.log_login_attempt(member_id, True)
                    return True

            self.log_login_attempt(member_id, False)
            return False

        except Exception as e:
            print(f"❌ Error verifying password for {member_id}: {e}")
            conn.close()
            return False

    def log_login_attempt(self, member_id, success):
        """Log login attempts"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO login_logs (member_id, success)
            VALUES (?, ?)
        ''', (member_id, success))

        conn.commit()
        conn.close()

    def get_all_users(self):
        """Get all users for management"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT member_id, name, date_of_birth, address, blood_group, phone, image_path,
                   membership_type, membership_joining_date, membership_renewal_date, created_at
            FROM users ORDER BY name
        ''')

        users = cursor.fetchall()
        conn.close()

        return [dict(user) for user in users]

    def add_user(self, user_data):
        """Add new user to database - UPDATED"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Set renewal date based on membership type
            if user_data.get('membership_type') == 'lifetime':
                renewal_date = '2099-12-31'
            else:
                # Calculate one year from joining date
                joining_date = user_data.get('membership_joining_date')
                if joining_date:
                    try:
                        join_dt = datetime.strptime(joining_date, '%Y-%m-%d')
                        renewal_dt = join_dt.replace(year=join_dt.year + 1)
                        renewal_date = renewal_dt.strftime('%Y-%m-%d')
                    except:
                        renewal_date = ''
                else:
                    renewal_date = ''

            cursor.execute('''
                INSERT INTO users 
                (member_id, name, date_of_birth, address, blood_group, phone, image_path,
                 membership_type, membership_joining_date, membership_renewal_date, password)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_data['member_id'],
                user_data['name'],
                user_data.get('date_of_birth', ''),
                user_data.get('address', ''),
                user_data.get('blood_group', ''),
                user_data.get('phone', ''),
                user_data.get('image_path', ''),
                user_data.get('membership_type', 'annually'),
                user_data.get('membership_joining_date', ''),
                renewal_date,
                user_data.get('password', '123456')
            ))

            conn.commit()
            conn.close()
            return True, "User added successfully!"
        except sqlite3.IntegrityError:
            conn.close()
            return False, "Member ID already exists!"
        except Exception as e:
            conn.close()
            return False, f"Error adding user: {str(e)}"

    def update_user(self, member_id, user_data):
        """Update user data - UPDATED"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Set renewal date based on membership type
            if user_data.get('membership_type') == 'lifetime':
                renewal_date = '2099-12-31'
            else:
                # Calculate one year from joining date
                joining_date = user_data.get('membership_joining_date')
                if joining_date:
                    try:
                        join_dt = datetime.strptime(joining_date, '%Y-%m-%d')
                        renewal_dt = join_dt.replace(year=join_dt.year + 1)
                        renewal_date = renewal_dt.strftime('%Y-%m-%d')
                    except:
                        renewal_date = user_data.get('membership_renewal_date', '')
                else:
                    renewal_date = user_data.get('membership_renewal_date', '')

            cursor.execute('''
                UPDATE users SET 
                name = ?, date_of_birth = ?, address = ?, blood_group = ?, phone = ?, image_path = ?,
                membership_type = ?, membership_joining_date = ?, membership_renewal_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE member_id = ?
            ''', (
                user_data['name'],
                user_data.get('date_of_birth', ''),
                user_data.get('address', ''),
                user_data.get('blood_group', ''),
                user_data.get('phone', ''),
                user_data.get('image_path', ''),
                user_data.get('membership_type', 'annually'),
                user_data.get('membership_joining_date', ''),
                renewal_date,
                member_id
            ))

            conn.commit()
            conn.close()

            if cursor.rowcount > 0:
                return True, "User updated successfully!"
            else:
                return False, "User not found!"

        except Exception as e:
            conn.close()
            return False, f"Error updating user: {str(e)}"

    def bulk_update_users(self, updates_data):
        """Bulk update multiple users"""
        conn = self.get_connection()
        cursor = conn.cursor()

        success_count = 0
        errors = []

        for member_id, update_data in updates_data.items():
            try:
                # Build dynamic update query based on provided fields
                set_clause = []
                params = []

                for field, value in update_data.items():
                    if field in ['name', 'date_of_birth', 'address', 'blood_group', 'phone',
                                 'image_path', 'membership_type', 'membership_joining_date']:
                        set_clause.append(f"{field} = ?")
                        params.append(value)

                # Handle renewal date based on membership type
                if 'membership_type' in update_data:
                    if update_data['membership_type'] == 'lifetime':
                        set_clause.append("membership_renewal_date = ?")
                        params.append('2099-12-31')
                    elif 'membership_joining_date' in update_data:
                        try:
                            join_dt = datetime.strptime(update_data['membership_joining_date'], '%Y-%m-%d')
                            renewal_dt = join_dt.replace(year=join_dt.year + 1)
                            set_clause.append("membership_renewal_date = ?")
                            params.append(renewal_dt.strftime('%Y-%m-%d'))
                        except:
                            pass

                set_clause.append("updated_at = CURRENT_TIMESTAMP")

                if set_clause:
                    query = f"UPDATE users SET {', '.join(set_clause)} WHERE member_id = ?"
                    params.append(member_id)

                    cursor.execute(query, params)
                    success_count += 1

            except Exception as e:
                errors.append(f"Error updating {member_id}: {str(e)}")

        conn.commit()
        conn.close()

        return success_count, errors

    def delete_user(self, member_id):
        """Delete user from database"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('DELETE FROM login_logs WHERE member_id = ?', (member_id,))
            cursor.execute('DELETE FROM users WHERE member_id = ?', (member_id,))

            conn.commit()
            conn.close()

            if cursor.rowcount > 0:
                return True, "User deleted successfully!"
            else:
                return False, "User not found!"

        except Exception as e:
            conn.close()
            return False, f"Error deleting user: {str(e)}"

    def verify_admin(self, username, password):
        """Verify admin credentials"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT password FROM admin_users WHERE username = ?
        ''', (username,))

        result = cursor.fetchone()
        conn.close()

        return result and result[0] == password

    def get_user_stats(self):
        """Get statistics about users"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(DISTINCT member_id) FROM login_logs 
            WHERE login_time >= datetime('now', '-7 days') AND success = 1
        ''')
        recent_logins = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(*) FROM users 
            WHERE date(membership_renewal_date) BETWEEN date('now') AND date('now', '+30 days')
            AND membership_type = 'annually'
        ''')
        renewal_soon = cursor.fetchone()[0]

        conn.close()

        return {
            'total_users': total_users,
            'recent_logins': recent_logins,
            'renewal_soon': renewal_soon
        }

    def reset_all_passwords(self, new_password='123456'):
        """Reset all user passwords to fix login issues"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('UPDATE users SET password = ?', (new_password,))
            conn.commit()
            conn.close()
            print(f"✅ All passwords reset to: {new_password}")
            return True
        except Exception as e:
            print(f"❌ Error resetting passwords: {e}")
            conn.close()
            return False

    def print_all_data(self):
        """Simple function to print all user data from database"""
        conn = self.get_connection()
        cursor = conn.cursor()

        print("\n" + "=" * 80)
        print("📋 ALL USER DATA FROM DATABASE")
        print("=" * 80)

        cursor.execute('''
            SELECT member_id, name, date_of_birth, blood_group, phone, 
                   membership_type, membership_joining_date, membership_renewal_date
            FROM users 
            ORDER BY member_id
        ''')

        users = cursor.fetchall()

        if not users:
            print("❌ No users found in database!")
            conn.close()
            return

        # Print header
        print(
            f"{'Member ID':<10} {'Name':<20} {'DOB':<12} {'Blood':<6} {'Phone':<12} {'Type':<10} {'Renewal Date':<12}")
        print("-" * 90)

        # Print each user
        for user in users:
            user_dict = dict(user)
            print(f"{user_dict['member_id']:<10} {user_dict['name']:<20} {user_dict['date_of_birth'] or '-':<12} "
                  f"{user_dict['blood_group'] or '-':<6} {user_dict['phone'] or '-':<12} "
                  f"{user_dict['membership_type'] or '-':<10} {user_dict['membership_renewal_date'] or '-':<12}")

        print(f"\nTotal users: {len(users)}")
        print("=" * 80)
        conn.close()

    def force_import_from_excel(self, file_path='users.xlsx'):
        """Force import from Excel file"""
        return self.import_from_excel(file_path)

    def change_user_password(self, member_id, new_password):
        """Change user password - ADMIN ONLY"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                UPDATE users SET password = ?, updated_at = CURRENT_TIMESTAMP
                WHERE member_id = ?
            ''', (new_password, member_id))

            conn.commit()
            conn.close()

            if cursor.rowcount > 0:
                return True, "Password changed successfully!"
            else:
                return False, "User not found!"

        except Exception as e:
            conn.close()
            return False, f"Error changing password: {str(e)}"

    def change_own_password(self, member_id, current_password, new_password):
        """Change own password with current password verification"""
        # First verify current password
        if not self.verify_password(member_id, current_password):
            return False, "Current password is incorrect!"

        # Then change password
        return self.change_user_password(member_id, new_password)

    def search_users(self, search_term):
        """Search users by name, member_id, or phone"""
        conn = self.get_connection()
        cursor = conn.cursor()

        search_pattern = f'%{search_term}%'

        cursor.execute('''
            SELECT member_id, name, date_of_birth, address, blood_group, phone, image_path,
                   membership_type, membership_joining_date, membership_renewal_date, created_at
            FROM users 
            WHERE name LIKE ? OR member_id LIKE ? OR phone LIKE ?
            ORDER BY name
        ''', (search_pattern, search_pattern, search_pattern))

        users = cursor.fetchall()
        conn.close()

        return [dict(user) for user in users]

    def bulk_update_users(self, updates_data):
        """Bulk update multiple users - FIXED to recalculate renewal date when membership_type changes"""
        conn = self.get_connection()
        cursor = conn.cursor()

        success_count = 0
        errors = []

        for member_id, update_data in updates_data.items():
            try:
                set_clause = []
                params = []

                for field, value in update_data.items():
                    if field in [
                        'name', 'date_of_birth', 'address', 'blood_group', 'phone',
                        'image_path', 'membership_type', 'membership_joining_date', 'membership_renewal_date'
                    ]:
                        set_clause.append(f"{field} = ?")
                        params.append(value)

                # 🔹 Auto-handle renewal date logic
                if 'membership_type' in update_data:
                    if update_data['membership_type'] == 'lifetime':
                        set_clause.append("membership_renewal_date = ?")
                        params.append('2099-12-31')
                    else:
                        # Fetch the user's joining date from DB
                        cursor.execute("SELECT membership_joining_date FROM users WHERE member_id = ?", (member_id,))
                        row = cursor.fetchone()
                        joining_date = None
                        if row and row['membership_joining_date']:
                            joining_date = row['membership_joining_date']

                        # Calculate renewal date one year after joining
                        if joining_date:
                            try:
                                from datetime import datetime
                                join_dt = datetime.strptime(joining_date, '%Y-%m-%d')
                                renewal_dt = join_dt.replace(year=join_dt.year + 1)
                                set_clause.append("membership_renewal_date = ?")
                                params.append(renewal_dt.strftime('%Y-%m-%d'))
                            except Exception as e:
                                print(f"⚠️ Could not calculate renewal date for {member_id}: {e}")

                set_clause.append("updated_at = CURRENT_TIMESTAMP")

                if set_clause:
                    query = f"UPDATE users SET {', '.join(set_clause)} WHERE member_id = ?"
                    params.append(member_id)
                    cursor.execute(query, params)
                    if cursor.rowcount > 0:
                        success_count += 1

            except Exception as e:
                errors.append(f"Error updating {member_id}: {str(e)}")

        conn.commit()
        conn.close()

        return success_count, errors

        conn.commit()
        conn.close()

        return success_count, errors

    def reload_all_images(self):
        """Reload all images from their URLs"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT member_id, image_path FROM users WHERE image_path IS NOT NULL AND image_path != ""')
        users_with_images = cursor.fetchall()

        reloaded_count = 0
        for user in users_with_images:
            member_id = user['member_id']
            image_path = user['image_path']

            print(f"🔄 Reloading image for {member_id} from {image_path}")
            image_data = self.get_image_from_url(image_path)
            if image_data:
                self.update_user_image(member_id, image_data)
                reloaded_count += 1
            else:
                print(f"❌ Failed to reload image for {member_id}")

        conn.close()
        print(f"✅ Reloaded {reloaded_count} images")
        return reloaded_count

    def convert_google_drive_url(self, url):
        """Convert Google Drive link to direct thumbnail-friendly image"""
        if not url:
            return None

        try:
            file_id = None
            if '/file/d/' in url:
                file_id = url.split('/file/d/')[1].split('/')[0]
            elif 'id=' in url:
                file_id = url.split('id=')[1].split('&')[0]
            elif '/open?id=' in url:
                file_id = url.split('/open?id=')[1].split('&')[0]

            if file_id:
                # Use thumbnail endpoint (works better for Drive images)
                return f"https://drive.google.com/thumbnail?id={file_id}&sz=w400"
            return url
        except Exception as e:
            print(f"❌ Error converting Google Drive URL: {e}")
            return url



db = UserDB()


