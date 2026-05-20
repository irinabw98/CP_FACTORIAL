<div align="center">

# 💜 CP_FACTORIAL
### ANOVA factorial dinámico + Tukey + Excel descargable

![Python](https://img.shields.io/badge/Python-3.11-7F3FBF?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-8A2BE2?style=for-the-badge&logo=fastapi&logoColor=white)
![Statsmodels](https://img.shields.io/badge/Statsmodels-ANOVA%20factorial-6A0DAD?style=for-the-badge)
![Render](https://img.shields.io/badge/Render-Online-A855F7?style=for-the-badge)
![Excel](https://img.shields.io/badge/Export-Excel-C084FC?style=for-the-badge)

Aplicación web para pegar datos desde Excel, configurar modelos factoriales y descargar resultados en formato Excel.

</div>

---

## ¿Qué hace esta app?

Permite:

- pegar una tabla copiada desde Excel o CSV;
- elegir la variable respuesta;
- seleccionar una cantidad variable de factores;
- definir factor principal y factor secundario para ordenar interpretación;
- elegir una columna de localidad o ambiente, por ejemplo `trial_mod`;
- analizar localidades:
  - separadas;
  - juntas como factor del modelo;
  - ambas formas;
- correr ANOVA factorial;
- generar comparaciones Tukey por efectos principales y por combinación factorial;
- descargar un Excel con resultados.

---

## Ejemplo de uso

Para un ensayo con 10 híbridos de maíz, tres dosis y dos localidades:

| Campo | Selección sugerida |
|---|---|
| Variable respuesta | `rendimiento` o `fitotoxicidad` |
| Factores | `hibrido`, `dosis` |
| Factor principal | `hibrido` |
| Factor secundario | `dosis` |
| Localidad / ambiente | `trial_mod` |
| Modo de localidades | `separadas`, `juntas` o `ambas` |

Si se selecciona modo **separadas**, la app corre:

```text
respuesta ~ hibrido * dosis
```

por cada localidad.

Si se selecciona modo **juntas**, la app corre:

```text
respuesta ~ trial_mod * hibrido * dosis
```

---

## Hojas del Excel generado

| Hoja | Contenido |
|---|---|
| `input_enriched` | tabla original con variable numérica estandarizada |
| `config` | configuración usada para el análisis |
| `anova_factorial` | tabla ANOVA con efectos principales e interacciones |
| `means_factorial` | medias por combinación de factores |
| `tukey_letters` | letras compactas de Tukey |
| `tukey_pairs` | detalle par a par de Tukey |
| `interpretacion` | resumen automático de efectos significativos |
| `warnings` | grupos que no pudieron analizarse |
| `diagnostics` | fitted values y residuos |

---

## Estructura del proyecto

```bash
CP_FACTORIAL/
├── app.py
├── app.js
├── index.html
├── styles.css
├── requirements.txt
├── runtime.txt
└── README.md
```

---

## Deploy sugerido

### Frontend

GitHub Pages con el repositorio:

```text
CP_FACTORIAL
```

### Backend

Render Web Service usando:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Luego actualizar en `app.js`:

```js
const API_BASE = "https://TU-BACKEND.onrender.com";
```

---

## Nota técnica

El backend usa `statsmodels` para ajustar modelos OLS con factores categóricos y ANOVA tipo II. Las columnas seleccionadas como factores se tratan como variables categóricas.

