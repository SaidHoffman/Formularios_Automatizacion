import pandas as pd

# Read all sheets
excel_file = pd.ExcelFile('Lista Verificación formularios URLs Aplicativos.xlsx')
print(f"📊 Sheet names: {excel_file.sheet_names}\n")

# Read Colombia sheet as example
df = pd.read_excel(excel_file, sheet_name='Colombia')
print("🇨🇴 Colombia Sheet Structure:")
print(f"Columns: {df.columns.tolist()}")
print(f"Shape: {df.shape}\n")
print("First 3 rows:")
print(df.head(3).to_string())
print("\n" + "="*80 + "\n")

# Check all column values
for col in df.columns:
    print(f"\n📋 Column: '{col}'")
    print(f"Non-null values: {df[col].notna().sum()}")
    print(f"Sample values:")
    print(df[col].dropna().head(3).to_list())
