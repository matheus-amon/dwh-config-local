# Data Platform Infrastructure

Infrastructure as Code (IaC) para o data lake e data warehouse no Google Cloud Platform.

## Recursos Criados

- **Google Cloud Storage Bucket**: Data Lake com lifecycle policies
- **BigQuery Datasets**: `data_warehouse` e `raw_data`
- **Service Account**: Para operações do pipeline de dados
- **IAM Permissions**: Acesso adequado aos recursos

## Como Usar

1. Copie o arquivo de exemplo:
```bash
cp terraform.tfvars.example terraform.tfvars
```

2. Edite o arquivo `terraform.tfvars` com seus valores:
```hcl
project_id          = "seu-projeto-gcp"
region              = "us-central1"
data_engineer_email = "seu-email@dominio.com"
```

3. Execute os comandos do Terraform:
```bash
terraform init
terraform plan
terraform apply
```

## Estrutura do Data Lake

O bucket será criado com a estrutura:
```
bucket/
├── year/
│   ├── month/
│   │   ├── day/
│   │   │   └── hour.parquet
```

## Lifecycle Policies

- Dados movidos para COLDLINE após 90 dias
- Dados movidos para ARCHIVE após 365 dias