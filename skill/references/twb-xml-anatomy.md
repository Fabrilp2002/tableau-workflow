# Anatomía del XML de Tableau (.twb)

Resumen práctico de la estructura interna de un archivo `.twb` para que Claude
pueda navegar y modificarlo con seguridad. Basado en workbooks reales de
your organization (versión 2025.2.5 / format 18.1).

## Estructura raíz

```xml
<workbook version='18.1' source-build='2025.2.5 (...)' source-platform='win'
          xmlns:user='http://www.tableausoftware.com/xml/user'>
  <preferences>...</preferences>
  <datasources>...</datasources>
  <worksheets>...</worksheets>
  <dashboards>...</dashboards>
  <windows>...</windows>
</workbook>
```

## Datasources

### Datasource publicada (Tableau Cloud)

```xml
<datasource caption='Survey - Region A'
            name='sqlproxy.1p6qlm81dc7ipk187tq1u09by8v4'
            inline='true'>
  <connection class='sqlproxy'
              dbname='Survey-RegionA'
              server='prod-useast-a.online.tableau.com'
              port='443'/>
  <!-- columns que el workbook usa de esta datasource -->
  <column datatype='string' name='[family_code]' role='dimension' type='nominal'/>
  <column datatype='real' name='[householdMonthlyIncome]' role='measure' type='quantitative'/>
  <!-- calculated fields -->
  <column caption='qty surveys' datatype='integer' name='[Calculation_xxx]' role='measure'>
    <calculation class='tableau' formula='COUNTD([survey_id])'/>
  </column>
</datasource>
```

**Claves para modificar**:
- Para clone+remap, cambiar `dbname='...'` por el LUID de la nueva datasource (y `caption` por su nombre humano).
- El `name='sqlproxy.{LUID}'` es el alias interno; cambiarlo también si cambia el LUID.

### Datasource de parámetros

```xml
<datasource caption='Parameters' name='Parameters' inline='true'>
  <column caption='Tipo de indicador' datatype='string'
          name='[Parameter 1]' param-domain-type='list' role='measure' type='nominal'
          value='&quot;Overall&quot;'>
    <aliases>
      <alias key='Overall' value='Overall'/>
      <alias key='Cumulative' value='Cumulative'/>
    </aliases>
    <members>
      <member value='&quot;Overall&quot;'/>
      <member value='&quot;Cumulative&quot;'/>
    </members>
  </column>
</datasource>
```

**Clave**: `param-domain-type` es el discriminador (`list` | `range` | `any`).

## Calculated Fields

Aparecen como `<column>` con un hijo `<calculation>`:

```xml
<column caption='income_monthly' datatype='integer' name='[Calculation_xxx]'
        role='measure' type='quantitative'>
  <calculation class='tableau' formula='INT([householdMonthlyIncome])'/>
</column>
```

**Referencias en fórmulas**:
- Campos de datasource: `[fieldName]`
- Otros calc fields: `[Calculation_xxx]` (IDs generados) o por caption
- Parámetros: `[Parameters].[Parameter 1]`
- Funciones agregadas: `SUM`, `COUNT`, `COUNTD`, `AVG`, `MIN`, `MAX`
- LOD expressions: `{FIXED [dim1], [dim2]: SUM([metric])}`, `{INCLUDE ...}`, `{EXCLUDE ...}`

**Cuando hacer remap**: la regex `\[([^\[\]]+)\]` extrae todas las refs. Diferenciar:
- Si la ref está dentro de `[Parameters].[X]` → es un parámetro, no remapear
- Si no, es un campo o calc field → remapear si está en el mapping

## Worksheets

```xml
<worksheet name='Base line'>
  <table>
    <view>
      <datasources>
        <datasource caption='Survey - Region A' name='sqlproxy.xxx'/>
      </datasources>
      <datasource-dependencies datasource='sqlproxy.xxx'>
        <column datatype='string' name='[family_code]' role='dimension'/>
      </datasource-dependencies>
      <slices>
        <column>[Parameters].[Parameter 1]</column>
      </slices>
      <filter class='categorical' column='[Federated.xxx].[organization]'
              filter-group='2'>  <!-- filter-group=2 = context filter -->
        ...
      </filter>
      <aggregation value='true'/>
    </view>
    <style>...</style>
    <panes>
      <pane>
        <mark class='Bar'/>
        ...
      </pane>
    </panes>
    <rows>SUM([householdMonthlyIncome])</rows>
    <cols>[family_code]</cols>
  </table>
</worksheet>
```

**Claves**:
- `<rows>` y `<cols>` contienen las pills del shelf (con sus agregaciones)
- `<filter filter-group='2'>` indica context filter
- `<mark class='Bar'>` define el tipo de marca

## Dashboards

```xml
<dashboard name='Indicator Overview'>
  <size maxheight='800' maxwidth='1200' .../>
  <zones>
    <zone h='400' type='view' w='600' x='0' y='0'>
      <view>
        <worksheet name='BvA.AreaOfResidence'/>
      </view>
    </zone>
    <zone h='400' type='layout-flow' .../>  <!-- containers -->
  </zones>
</dashboard>
```

**Para componer**: cada zone con `type='view'` referencia un `<worksheet name='...'/>`. Para incorporar un sheet de otro workbook, hay que:
1. Copiar el bloque `<worksheet>` completo al workbook destino
2. Copiar también su datasource-dependencies y calc fields referenciados
3. Agregar una zone que lo referencie en el dashboard destino

## Operaciones seguras

| Operación | Riesgo | Notas |
|---|---|---|
| Cambiar `caption` de datasource | Bajo | Solo display |
| Cambiar `dbname` y `name` de datasource | Medio | Hay que cambiar también las refs en sheets (`<datasource name='sqlproxy.xxx'/>`) |
| Remap de campo en `<column name='[X]'>` | Medio | Hay que cambiar en TODOS los lugares: columns, rows/cols, datasource-dependencies, fórmulas, filtros |
| Cambiar fórmula de calc field | Bajo | Solo si Claude entiende la sintaxis Tableau |
| Agregar context filter | Bajo | Cambiar `filter-group` a `'2'` en un filter existente |
| Mover/clonar worksheets | Alto | Requiere arrastrar todas las dependencias (calc fields, params, filtros) |

## Validación pre-publish recomendada

1. **Parse OK**: `xml.etree.ElementTree.parse()` no tira excepción.
2. **Datasource refs consistentes**: cada `<worksheet>` referencia datasources que existen en `<datasources>`.
3. **Field refs en sheets existen en datasource-dependencies o calc_fields**.
4. **Calc fields no tienen refs huérfanas**: cada `[X]` en una fórmula apunta a algo que existe.
5. **Parámetros referenciados existen** en el datasource `Parameters`.
