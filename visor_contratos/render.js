/* Motor de bloques compartido (bug 055): antes vivía copiado dentro de
   visor_contratos/plantilla.html; ahora es el ÚNICO fichero, cargado con
   <script src="/render.js"> por el visor de contratos y por el de
   presentaciones (unidad 056). Sin librerías externas, sin módulos: son
   declaraciones de función sueltas para poder cargarse con un <script>
   normal en el navegador y para que los tests de Node las lean tal cual. */

/* ---------- Markdown mínimo ----------
   El Markdown que renderiza este motor es simple y conocido: encabezados,
   listas (con casillas), tablas, citas, bloques de código y negritas. Con eso
   basta; no se trae una librería para esto. */

function esc(t) {
  return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function enLinea(t) {
  var salida = "";
  var resto = esc(t);
  // El código va primero: dentro de `...` no se interpreta nada más.
  var trozos = resto.split(/(`[^`]+`)/);
  for (var i = 0; i < trozos.length; i++) {
    var trozo = trozos[i];
    if (trozo.charAt(0) === "`" && trozo.length > 1) {
      salida += "<code>" + trozo.slice(1, -1) + "</code>";
      continue;
    }
    trozo = trozo.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
      function (_, texto, url) {
        if (!/^(https?:|#)/.test(url)) return texto;  // sin rutas locales
        return '<a href="' + url + '" rel="noreferrer">' + texto + "</a>";
      });
    trozo = trozo.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    trozo = trozo.replace(/(^|[\s(])_([^_]+)_(?=[\s.,;:)]|$)/g, "$1<em>$2</em>");
    salida += trozo;
  }
  return salida;
}

function fila(linea, celda) {
  var partes = linea.trim().replace(/^\|/, "").replace(/\|$/, "").split("|");
  var html = "<tr>";
  for (var i = 0; i < partes.length; i++) {
    html += "<" + celda + ">" + enLinea(partes[i].trim()) + "</" + celda + ">";
  }
  return html + "</tr>";
}

function bloques(lineas) {
  var html = "";
  var i = 0;
  while (i < lineas.length) {
    var linea = lineas[i];
    var limpia = linea.trim();

    if (!limpia) { i++; continue; }

    if (/^```/.test(limpia)) {
      var codigo = [];
      i++;
      while (i < lineas.length && !/^```/.test(lineas[i].trim())) {
        codigo.push(esc(lineas[i]));
        i++;
      }
      i++;
      html += "<pre><code>" + codigo.join("\n") + "</code></pre>";
      continue;
    }

    var enc = /^(#{3,6})\s+(.*)$/.exec(limpia);
    if (enc) {
      var nivel = Math.min(enc[1].length + 1, 6);
      html += "<h" + nivel + ">" + enLinea(enc[2]) + "</h" + nivel + ">";
      i++;
      continue;
    }

    if (limpia.charAt(0) === "|") {
      var filas = [];
      while (i < lineas.length && lineas[i].trim().charAt(0) === "|") {
        filas.push(lineas[i]);
        i++;
      }
      var separador = filas.length > 1 && /^\|[\s:|-]+\|$/.test(filas[1].trim());
      html += "<table>";
      if (separador) {
        html += "<thead>" + fila(filas[0], "th") + "</thead><tbody>";
        for (var f = 2; f < filas.length; f++) html += fila(filas[f], "td");
        html += "</tbody>";
      } else {
        html += "<tbody>";
        for (var g = 0; g < filas.length; g++) html += fila(filas[g], "td");
        html += "</tbody>";
      }
      html += "</table>";
      continue;
    }

    if (/^>\s?/.test(limpia)) {
      var cita = [];
      while (i < lineas.length && /^>\s?/.test(lineas[i].trim())) {
        cita.push(lineas[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      html += "<blockquote>" + bloques(cita) + "</blockquote>";
      continue;
    }

    if (/^([-*]|\d+\.)\s+/.test(limpia)) {
      var ordenada = /^\d+\.\s+/.test(limpia);
      var items = [];
      while (i < lineas.length) {
        var actual = lineas[i];
        var suya = actual.trim();
        if (/^([-*]|\d+\.)\s+/.test(suya) && !/^\s\s+/.test(actual)) {
          items.push([suya.replace(/^([-*]|\d+\.)\s+/, "")]);
        } else if (items.length && suya && /^\s+/.test(actual)) {
          items[items.length - 1].push(suya);  // continuación sangrada
        } else {
          break;
        }
        i++;
      }
      html += ordenada ? "<ol>" : "<ul>";
      for (var k = 0; k < items.length; k++) {
        var texto = items[k].join(" ");
        var tarea = /^\[( |x|X)\]\s*/.exec(texto);
        if (tarea) {
          var hecha = tarea[1].toLowerCase() === "x";
          html += '<li class="tarea' + (hecha ? " hecha" : "") + '">' +
                  '<span class="caja">' + (hecha ? "☑" : "☐") + "</span>" +
                  enLinea(texto.replace(/^\[( |x|X)\]\s*/, "")) + "</li>";
        } else {
          html += "<li>" + enLinea(texto) + "</li>";
        }
      }
      html += ordenada ? "</ol>" : "</ul>";
      continue;
    }

    /* Párrafo. La primera línea se toma SIEMPRE: si llegó aquí es que ninguna
       rama anterior la consumió (una negrita a principio de párrafo, una raya
       `---`, un `# ` repetido…) y dejarla sin avanzar `i` colgaba la página
       (bug 055). Las siguientes se cortan donde empieza otro bloque. */
    var parrafo = [limpia];
    i++;
    while (i < lineas.length) {
      var p = lineas[i].trim();
      if (!p || /^([-*>|#]|\d+\.\s)/.test(p) || /^```/.test(p)) break;
      parrafo.push(p);
      i++;
    }
    html += "<p>" + enLinea(parrafo.join(" ")) + "</p>";
  }
  return html;
}
