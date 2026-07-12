## Template local (exemplo) - NÃO VERSIONAR

# Este arquivo é um exemplo. O arquivo real deve se chamar `claude_local.md` e ficar na raiz do projeto.
# `claude_local.md` deve ser incluído no `.gitignore` e NÃO deve ser commitado.

---

tuya_cloud:
  api_key: "<TUYA_ACCESS_ID>"
  api_secret: "<TUYA_ACCESS_SECRET>"
  region: "us" # ou eu, cn, etc.
  timezone: "America/Sao_Paulo"

python_env:
  venv_path: "C:\\Projetos\\rolloff-tuya-control\\.venv"

devices:
  - name: "Pier 1 - Cobertura"
    id: "DEVICE_ID_PIER1"
    ip: "192.168.1.101"
    key: "LOCAL_KEY_PIER1"
    category: "ckmkzq"
    version: 3.4

  - name: "Pier 1 - Regua"
    id: "DEVICE_ID_REGUA"
    ip: "192.168.1.102"
    key: "LOCAL_KEY_REGUA"
    category: "xxxxxx"
    version: 3.4

piers:
  pier1:
    coverage_device: "DEVICE_ID_PIER1"
    ruler_device: "DEVICE_ID_REGUA"
    notes: "Instruções locais específicas do pier 1"

contact:
  - name: "Operador Principal"
    phone: "+55 11 9XXXX-XXXX"
    email: "nome@observatorio.org"

notes: |
  - Horário padrão de fechamento: 05:00
  - Recomendação de segurança: configurar timer cloud como redundância
