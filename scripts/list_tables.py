import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    db_url = "postgresql+asyncpg://cargaexpress_admin:edK%25ER08hzu9q%23%5DPZMlQNw%7Bv@localhost:5433/cargaexpress_staging"
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'carriers';"))
        cols = [r[0] for r in res.fetchall()]
        print("Columns in carriers:", cols)
        
        c_res = await conn.execute(text("SELECT carrier_id, name, integration_type FROM carriers ORDER BY carrier_id;"))
        carriers = c_res.fetchall()
        print(f"\nTOTAL SEEDED CARRIERS: {len(carriers)}")
        for c in carriers:
            print(f"  Carrier #{c[0]}: {c[1]} (Type: {c[2]})")

        sm_res = await conn.execute(text("SELECT count(*) FROM state_mapping;"))
        count = sm_res.scalar()
        print(f"\nTOTAL STATE MAPPINGS SEEDED: {count}")
            
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
