"""
Capa delgada de compatibilidad Databricks / local.

En Databricks (serverless) usa Unity Catalog, Delta Lake y las funciones H3
nativas de Spark SQL. Fuera de Databricks (pruebas locales) crea una sesión
Spark, guarda tablas en Parquet y registra equivalentes Python de las
funciones H3, de modo que el SQL de los notebooks es idéntico en ambos casos.
"""
import os

from . import config as C


def is_databricks() -> bool:
    return "DATABRICKS_RUNTIME_VERSION" in os.environ


def volume_path() -> str:
    return os.environ.get("GEOCLOUD_VOLUME", C.VOLUME_PATH)


def tbl(name: str) -> str:
    """Nombre totalmente calificado de una tabla."""
    return f"{C.CATALOG}.{C.SCHEMA}.{name}" if is_databricks() else f"{C.SCHEMA}.{name}"


def get_spark():
    from pyspark.sql import SparkSession
    if is_databricks():
        return SparkSession.builder.getOrCreate()
    wh = os.path.abspath(os.environ.get("GEOCLOUD_WAREHOUSE", "spark-warehouse"))
    spark = (SparkSession.builder.master("local[*]").appName("geocloud-local")
             .config("spark.sql.warehouse.dir", wh)
             .config("javax.jdo.option.ConnectionURL", f"jdbc:derby:;databaseName={wh}/metastore_db;create=true")
             .enableHiveSupport()
             .config("spark.sql.shuffle.partitions", "8")
             .config("spark.sql.execution.arrow.pyspark.enabled", "true")
             .config("spark.driver.memory", "6g")
             .config("spark.driver.extraJavaOptions",
                     "--add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/sun.nio.ch=ALL-UNNAMED "
                     "-Dio.netty.tryReflectionSetAccessible=true")
             .getOrCreate())
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {C.SCHEMA}")
    register_h3_fallbacks(spark)
    return spark


def setup_catalog(spark):
    """Crea esquema y Volume si no existen (idempotente)."""
    if is_databricks():
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {C.CATALOG}.{C.SCHEMA}")
        spark.sql(f"CREATE VOLUME IF NOT EXISTS {C.CATALOG}.{C.SCHEMA}.{C.VOLUME}")
    else:
        spark.sql(f"CREATE DATABASE IF NOT EXISTS {C.SCHEMA}")


def save_table(df, name: str, partition_by=None, mode: str = "overwrite"):
    fmt = "delta" if is_databricks() else "parquet"
    w = df.write.format(fmt).mode(mode).option("overwriteSchema", "true")
    if partition_by:
        w = w.partitionBy(*([partition_by] if isinstance(partition_by, str) else partition_by))
    w.saveAsTable(tbl(name))
    return tbl(name)


def register_h3_fallbacks(spark):
    """Equivalentes Python (solo local) de las funciones H3 nativas de Databricks."""
    import h3
    import pandas as pd
    from pyspark.sql.functions import pandas_udf
    from pyspark.sql.types import ArrayType, StringType

    @pandas_udf(StringType())
    def h3_longlatash3string(lon: pd.Series, lat: pd.Series, res: pd.Series) -> pd.Series:
        r = int(res.iloc[0])
        return pd.Series([h3.latlng_to_cell(la, lo, r) for lo, la in zip(lon, lat)])

    @pandas_udf(StringType())
    def h3_toparent(cell: pd.Series, res: pd.Series) -> pd.Series:
        r = int(res.iloc[0])
        return cell.map(lambda c: h3.cell_to_parent(c, r))

    @pandas_udf(ArrayType(StringType()))
    def h3_kring(cell: pd.Series, k: pd.Series) -> pd.Series:
        kk = int(k.iloc[0])
        return cell.map(lambda c: list(h3.grid_disk(c, kk)))

    spark.udf.register("h3_longlatash3string", h3_longlatash3string)
    spark.udf.register("h3_toparent", h3_toparent)
    spark.udf.register("h3_kring", h3_kring)


def show(df, n: int = 20):
    """display() en Databricks, show() en local."""
    try:
        display(df)  # noqa: F821  (definida por Databricks)
    except NameError:
        if hasattr(df, "show"):
            df.show(n, truncate=False)
        else:
            print(df.head(n).to_string())


def clean(pdf):
    """
    Limpia los metadatos que Spark Connect (serverless) adjunta a un pandas.DataFrame
    en df.attrs (métricas del plan). Si no se limpian, spark.createDataFrame(pdf)
    falla con 'PlanMetrics is not JSON serializable'.
    """
    pdf.attrs = {}
    return pdf
