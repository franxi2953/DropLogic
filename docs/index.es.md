<div class="dl-home">
  <div class="dl-home__mark" aria-hidden="true">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" fill="none">
      <circle cx="34" cy="48" r="24" fill="white" stroke="#111111" stroke-width="4"/>
      <circle cx="62" cy="48" r="24" fill="white" stroke="#111111" stroke-width="4"/>
      <path d="M48 28.5A24 24 0 0 0 48 67.5A24 24 0 0 0 48 28.5Z" fill="#111111"/>
    </svg>
  </div>
  <p class="dl-home__eyebrow">Plataforma de control para microfluídica digital</p>
  <h1 class="dl-home__title">DropLogic</h1>
  <p class="dl-home__copy">
    Control minimalista y listo para despliegue en microfluidica digital: sistemas, planificacion, ejecucion, visualizacion y utilidades dentro de una sola libreria.
  </p>
  <div class="dl-home__actions">
    <a class="md-button dl-button" href="getting_started/">Empezando</a>
    <a class="md-button dl-button" href="systems/">Sistemas</a>
    <a class="md-button dl-button" href="planning/">Planificacion</a>
    <a class="md-button dl-button" href="visualization/">Visualizacion</a>
  </div>
</div>

!!! warning "Compatibilidad"
    **Actualmente, DropLogic solo es compatible con Windows.** La librería utiliza controladores e interconexiones de hardware en forma de DLLs propietarios brindados por los fabricantes, los cuales son exclusivos de Windows. Usar la librería en macOS o Linux causará errores tanto a nivel de dependencias como de ejecución.

¡Bienvenido a la documentación oficial de **DropLogic**! Hemos creado esta plataforma para hacer que el control de la microfluídica digital (DMF) sea lo más sencillo posible. En lugar de lidiar con diferentes interfaces de hardware, DropLogic abstrae los módulos de hardware (como matrices de electrodos, cámaras y sistemas de posicionamiento) en una única librería unificada, proporcionando clases comunes diseñadas específicamente para aplicaciones de microfluídica digital. Ya sea que estés moviendo unas pocas gotas o automatizando todo el flujo de trabajo de un laboratorio, esta herramienta te ofrece el control de alto nivel que necesitas para centrarte en tus experimentos.

## ¿Qué encontrarás aquí?
<ul class="dl-home__list">
  <li><strong><a href="getting_started/">Empezando</a></strong>: Instalación, uso básico y primeros pasos.</li>
  <li><strong><a href="repository_structure/">Mapa de Arquitectura</a></strong>: Una mirada detallada a la estructura de la librería y su organización de hardware.</li>
  <li><strong><a href="systems/">Sistemas</a></strong>: La estructura de sistemas, módulos, versiones y cómo crear máquinas nuevas.</li>
  <li><strong><a href="planning/">Planificacion</a></strong>: AdvancedDrop, planes de gotas, movimiento SIPP y ejecucion en runtime.</li>
  <li><strong><a href="visualization/">Visualizacion</a></strong>: Visualizadores de matriz y streamer, snapshots y grabacion sincronizada.</li>
  <li><strong><a href="utilities/">Utilidades</a></strong>: Calibracion, vision de gotas, helpers de hardware, depuracion y diagnosticos.</li>
</ul>
