<div class="dl-home">
  <div class="dl-home__mark" aria-hidden="true">
    <img src="../assets/droplets-mark.svg" alt="">
  </div>
  <p class="dl-home__eyebrow">Librería Python para microfluídica digital</p>
  <h1 class="dl-home__title">DropLogic</h1>
  <p class="dl-home__copy">
    Control minimalista y listo para despliegue en microfluidica digital: sistemas, planificacion, ejecucion, visualizacion y utilidades dentro de una sola libreria.
  </p>
  <div class="dl-home__actions">
    <a class="md-button dl-button" href="getting_started/">Empezando</a>
    <a class="md-button dl-button" href="systems/">Sistemas</a>
    <a class="md-button dl-button" href="planning/">Planificacion</a>
    <a class="md-button dl-button" href="visualization/">Visualizacion</a>
    <a class="md-button dl-button" href="mcp/">Control por Agentes</a>
  </div>
</div>

!!! warning "Compatibilidad"
    **El control nativo de DMLite actualmente solo esta soportado en Windows.** La libreria utiliza DLLs propietarias proporcionadas por proveedores de hardware. En macOS, `DMLite()` lanza intencionadamente un error claro por ahora; usa el `Simulator` alli hasta que exista un backend macOS soportado.

Bienvenido a la documentación de **DropLogic**, una librería Python para control de microfluídica digital (DMF). Mantiene los scripts legibles agrupando sistemas, módulos, planificación, ejecución y visualización detrás de una interfaz Python compartida. En lugar de lidiar con distintas interfaces de hardware, trabajas con clases comunes para matrices de electrodos, cámaras, sistemas de posicionamiento y planes de gotas.

## ¿Qué encontrarás aquí?
<ul class="dl-home__list">
  <li><strong><a href="getting_started/">Empezando</a></strong>: Instalación, uso básico y primeros pasos.</li>
  <li><strong><a href="configuration/">Configuracion</a></strong>: El `config.json` del repositorio, campos obligatorios y calibracion local especifica de maquina.</li>
  <li><strong><a href="repository_structure/">Mapa de Arquitectura</a></strong>: Una mirada detallada a la estructura de la librería y su organización de hardware.</li>
  <li><strong><a href="systems/">Sistemas</a></strong>: La estructura de sistemas, módulos, versiones y cómo crear máquinas nuevas.</li>
  <li><strong><a href="planning/">Planificacion</a></strong>: AdvancedDrop, planes de gotas, movimiento SIPP y ejecucion en runtime.</li>
  <li><strong><a href="visualization/">Visualizacion</a></strong>: Visualizadores de matriz y streamer, snapshots y grabacion sincronizada.</li>
  <li><strong><a href="mcp/">Control por Agentes</a></strong>: Servidor MCP para que agentes planifiquen, ejecuten, inspeccionen frames y lancen vision.</li>
  <li><strong><a href="utilities/">Utilidades</a></strong>: Helpers de hardware, vision de gotas, depuracion y diagnosticos.</li>
</ul>
