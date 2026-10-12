# Phase 4のSchema Evolution比較用Data Flow。
# Strictの比較対象は本番のdf_transform_orders（allowSchemaDrift: false・validateSchema: true）を使い、
# ここでは設定だけを変えた3つを追加する。Debugで比較するため、Pipeline・Triggerからは参照しない。
locals {
  schema_evolution_data_flows = {
    # 宣言外の列を無視し、宣言した列が合わなくても失敗させない。
    df_schema_tolerant = {
      script          = "tolerant.dfsql"
      transformations = ["RenameColumns", "ConvertTypes", "DropInvalidRows"]
    }
    # 宣言外の列をstringのまま出力まで通す。
    df_schema_drift = {
      script          = "drift.dfsql"
      transformations = ["ConvertTypes", "DropInvalidRows", "DropSourceNames"]
    }
    # 宣言外の列の型を値から推論して通す。
    df_schema_drift_infer = {
      script          = "drift_infer.dfsql"
      transformations = ["ConvertTypes", "DropInvalidRows", "DropSourceNames"]
    }
  }
}

resource "azurerm_data_factory_data_flow" "schema_evolution" {
  for_each = var.data_factory_enabled && var.schema_evolution_lab_enabled ? local.schema_evolution_data_flows : {}

  name            = each.key
  data_factory_id = azurerm_data_factory.lab[0].id
  folder          = "schema-evolution"
  script          = file("${path.module}/adf/schema-evolution/${each.value.script}")

  source {
    name = "source1"
    dataset {
      name = azurerm_data_factory_dataset_delimited_text.csv[0].name
    }
  }

  # script内の変換は名前だけ宣言しないとtransformationsがnullになり、sinkまで実行されない。
  dynamic "transformation" {
    for_each = each.value.transformations
    content {
      name = transformation.value
    }
  }

  sink {
    name = "sink1"
    dataset {
      name = azurerm_data_factory_dataset_delimited_text.csv[0].name
    }
  }
}
