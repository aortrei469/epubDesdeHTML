# Generador de EPUB desde HTML

Convierte un conjunto de páginas HTML, CSS e imágenes en un archivo EPUB3 válido que supera la validación estructural de `epubcheck`.

## Requisitos

- Python 3.10+
- Dependencias Python (se instalan automáticamente, ver [Instalación](#instalacin))

## Estructura del proyecto

```
epubDesdeHtml/
├── generar_epub.py       # Script principal
├── requirements.txt      # Dependencias Python
├── env/                  # Entorno virtual (se crea en la instalación)
├── libro/                # Directorio fuente del libro
    ├── *.html            # Páginas del libro 
    ├── css/
    │   └── resultado.css # Estilos
    └── images/           # Imágenes 
        ├── 
        ├── 
        ├── 
        └── *.png, *.jpg, *.jpeg  (imágenes sueltas)
```

## Instalación

```bash
# 1. Crear el entorno virtual e instalar dependencias
python3 -m venv env
./env/bin/pip install -r requirements.txt

# (Alternativa) Un solo paso si el venv ya existe:
./env/bin/pip install -r requirements.txt
```

## Uso

```bash
./env/bin/python generar_epub.py
```

El script:

1. Escanea `libro/` en busca de archivos `*.html`, `css/*`, `images/**/*`
2. Ordena las páginas alfabéticamente (mismo orden que `ls -1`)
3. Convierte cada HTML5 a XHTML válido (sin modificar los originales)
4. Genera la estructura completa EPUB3 (`mimetype`, `META-INF/container.xml`, `OEBPS/content.opf`, `OEBPS/toc.xhtml`, `OEBPS/toc.ncx`)
5. Empaqueta todo en `libro.epub`

### Salida esperada

```
Páginas HTML: 58
CSS:          1
Imágenes:     355
  ✓ 00aa_primera_parte.html → Primera Parte
  ✓ 00bb_primera_parte.html → Introducción
  ...
  ✓ 51_bibliografia.html → Bibliografía

 EPUB generado: libro.epub
    ID: aaaabbbb-cccc-dddd-eeee-ffffffffffff
```

## Validación con epubcheck

```bash
epubcheck libro.epub
```

### Lo que el script garantiza (0 errores estructurales)

| Aspecto | Estado |
|---------|--------|
| `mimetype` primero y sin compresión | ✅ |
| `META-INF/container.xml` correcto | ✅ |
| `content.opf` con metadatos completos | ✅ |
| Namespaces `dc:`, `opf:` declarados | ✅ |
| `spine toc="ncx"` presente | ✅ |
| IDs XML válidos (no empiezan por dígito) | ✅ |
| Todos los archivos en el manifest | ✅ |
| Tabla de contenidos (`toc.xhtml` + `toc.ncx`) | ✅ |
| Documentos XHTML bien formados | ✅ |
| BOM (UTF-8 BOM) eliminado automáticamente | ✅ |
| Rutas duplicadas (case-insensitive) resueltas | ✅ |

### EJEMPLO de lo que queda a cargo del usuario

Los siguientes errores son de **contenido** y deben corregirse en los archivos fuente de `libro/`:

| Error | Archivo(s) | Causa |
|-------|-----------|-------|
| `Duplicate meta charset` | `06_OllamaHibrido_OpenRouterFree.html`, `07_Aider.html` | Dos `<meta charset="UTF-8">` en el mismo `<head>` |
| `Duplicate ID` | `15a_notebooklm.html` | Dos elementos con `id="notebooklm07"` |
| `Imagen corrupta` | `images/notebooklm/ntb01.jpg`–`ntb04.jpg` | Archivos JPEG inválidos |
| `WebP sin fallback` | `15a_notebooklm.html` | Referencia a `.webp` sin recurso de respaldo en el manifest |

## Personalización

Edita las constantes al inicio de `generar_epub.py` para cambiar metadatos del libro:

```python
BOOK_TITLE   = "..."
BOOK_AUTHOR  = "Arcadio Ortega Reinoso"
BOOK_LANG    = "es"
BOOK_PUBLISHER = "Autoedición"
```

## Cómo funciona

### Flujo de generación

```
libro/*.html  ──►  html5lib + lxml  ──►  XHTML válido  ──┐
libro/css/*   ──►  copia directa    ──►  css/           ├──► OEBPS/
libro/images/ ──►  copia directa    ──►  images/        ┘
                                                    │
                          ┌─── content.opf (manifiesto + spine)
                          ├─── toc.xhtml (nav)
                          ├─── toc.ncx   (legado)
                          └─── mimetype + META-INF/container.xml
                                                    │
                              zip -X (mimetype sin comprimir)
                                                    │
                                              libro.epub
```

### Estructura interna del EPUB

```
libro.epub
├── mimetype                    # application/epub+zip (ZIP_STORED, primero)
├── META-INF/
│   └── container.xml           # Apunta a OEBPS/content.opf
└── OEBPS/
    ├── content.opf             # Package document (EPUB3)
    ├── toc.xhtml               # Navegación (properties="nav")
    ├── toc.ncx                 # NCX para compatibilidad con lectores antiguos
    ├── css/
    │   └── resultado.css
    ├── images/
    │   └── ... (355 archivos)
    ├── 00aa_primera_parte.html
    ├── 00bb_primera_parte.html
    ├── ... (58 páginas)
    └── 51_bibliografia.html
```

### Conversión HTML → XHTML

1. Se elimina la BOM (U+FEFF) si existe
2. `html5lib` (con treebuilder `lxml`) parsea el HTML5 de forma tolerante
3. `lxml.etree.tostring(method="xml")` serializa a XHTML bien formado:
   - Etiquetas auto-cerradas: `<img/>`, `<br/>`, `<meta/>`
   - Atributos con comillas dobles
   - `<!DOCTYPE html>` y `<?xml version="1.0" encoding="utf-8"?>`
   - `xmlns="http://www.w3.org/1999/xhtml"` en el elemento `<html>`
4. Los archivos fuente **no se modifican**

### Resolución de duplicados case-insensitive

Cuando existen directorios como `Antigravity/` y `antigravity/`, el script:

1. Detecta que sus rutas normalizadas (en minúsculas) son idénticas
2. Conserva la versión con **menos mayúsculas** (la que coincide con las referencias en los HTML)
3. La otra versión se descarta silenciosamente

## Notas

- Las extensiones `.html` en lugar de `.xhtml` generan una advertencia en epubcheck (HTM-014a). Es inocua y no afecta la lectura en ningún dispositivo.
- Los IDs de los `<item>` en el manifest se generan a partir del nombre del archivo, prefijados con `p-` cuando empiezan por dígito para cumplir con la especificación XML (NCNames).
- El UUID del libro se genera aleatoriamente en cada ejecución.
