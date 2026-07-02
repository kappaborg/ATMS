Service URLs:
  - PostgreSQL:  localhost:5432
  - Redis:       localhost:6379
  - pgAdmin:     http://localhost:5050

📋 Connection Details:
  PostgreSQL:
    Database: atms
    User:     atms_user
    Password: atms_password

  Redis:
    Password: atms_redis_password

  pgAdmin:
    Email:    admin@example.com
    Password: admin

💡 To stop database services:
   docker-compose -f docker-compose.database.yml down

🧪 To test database connection:
   python database/database.py
   python database/redis_cache.py