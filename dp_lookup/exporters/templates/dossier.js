    const DATA = @@A0@@;

    // Initialize Leaflet Map
    const center = DATA.plot_identity.center;
    const map = L.map('map', {
      center: center,
      zoom: 18,
      zoomControl: false,
    });

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // High-Resolution Base Tile Layers
    const baseLayers = {
      sat: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Esri World Imagery',
        maxZoom: 19
      }),
      cad: L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; CartoDB &copy; OpenStreetMap',
        maxZoom: 19
      })
    };

    let currentBase = 'sat';
    baseLayers.sat.addTo(map);

    function setBase(key) {
      if (key === currentBase) return;
      map.removeLayer(baseLayers[currentBase]);
      baseLayers[key].addTo(map);
      currentBase = key;

      // Bring vector overlays to front
      Object.values(overlayLayers).forEach(layer => {
        if (map.hasLayer(layer) && layer.bringToFront) layer.bringToFront();
      });

      document.getElementById('btn-sat').classList.toggle('active', key === 'sat');
      document.getElementById('btn-cad').classList.toggle('active', key === 'cad');
      const floatBtn = document.getElementById('floatingSatBtn');
      if (floatBtn) floatBtn.textContent = key === 'sat' ? '🗺️' : '🛰️';
    }

    function toggleBaseImagery() {
      setBase(currentBase === 'sat' ? 'cad' : 'sat');
    }

    // Layer Storage
    const overlayLayers = {};

    // 1. Abutting Roads Layer (HIGH-CONTRAST ELECTRIC CYAN)
    overlayLayers.roads = L.geoJSON(DATA.roads, {
      style: {
        color: '#0284c7',
        weight: 6,
        opacity: 0.95,
        dashArray: '8, 6',
      },
      onEachFeature: (feature, layer) => {
        layer.bindPopup(`
          <div class="custom-popup">
            <h4 style="color:#0284c7">🛣️ Abutting Road Alignment</h4>
            <div><b>Road:</b> ${feature.properties.road_name}</div>
            <div><b>Width:</b> ${feature.properties.road_width}</div>
          </div>
        `);
      }
    }).addTo(map);

    // 2. Base Plot Boundary (VIVID CRIMSON RED with Corner Vertex Markers)
    overlayLayers.plot = L.geoJSON(DATA.base_plot, {
      style: {
        color: '#e11d48',
        weight: 3.5,
        opacity: 1.0,
        fillColor: '#e11d48',
        fillOpacity: 0.12,
      },
      onEachFeature: (feature, layer) => {
        layer.bindPopup(`
          <div class="custom-popup">
            <h4 style="color:#e11d48">🔴 Plot Boundary</h4>
            <div><b>CTS / CS No:</b> ${DATA.plot_identity.cts_no}</div>
            <div><b>Village:</b> ${DATA.plot_identity.village}</div>
            <div><b>Ward:</b> ${DATA.plot_identity.ward}</div>
            <div><b>Working plot area:</b> ${DATA.plot_identity.area_sqm.toLocaleString()} m² (${DATA.plot_identity.area_sqft.toLocaleString()} sq.ft)</div>
            <div><b>Area reliability:</b> ${DATA.plot_identity.area_assessment.reliability_label}</div>
            <div><b>Boundary source:</b> ${DATA.plot_identity.geometry_source}</div>
            <div><b>Zone:</b> Zone ${DATA.plot_identity.zone}</div>
          </div>
        `);
      }
    }).addTo(map);

    // Corner Vertex Markers
    if (DATA.base_plot.geometry && DATA.base_plot.geometry.coordinates[0]) {
      DATA.base_plot.geometry.coordinates[0].forEach((pt, i) => {
        L.circleMarker([pt[1], pt[0]], {
          radius: 4,
          color: '#e11d48',
          fillColor: '#ffffff',
          fillOpacity: 1.0,
          weight: 2
        }).bindTooltip(`Corner ${i + 1}: [${pt[1].toFixed(5)}, ${pt[0].toFixed(5)}]`).addTo(map);
      });
    }

    // 3. Net Developable Layer (EMERALD GREEN)
    overlayLayers.net = L.geoJSON(DATA.net_plot, {
      style: {
        color: '#059669',
        weight: 2.5,
        opacity: 0.9,
        fillColor: '#10b981',
        fillOpacity: 0.28,
      },
      onEachFeature: (feature, layer) => {
        layer.bindPopup(`
          <div class="custom-popup">
            <h4 style="color:#059669">🟢 Net Developable Envelope</h4>
            <div><b>Net Usable Area:</b> ${DATA.plot_identity.net_sqm.toLocaleString()} m²</div>
            <div><b>Percentage:</b> ${DATA.plot_identity.net_percent}% of working plot area</div>
            <div><b>Status:</b> Unencumbered Zone ${DATA.plot_identity.zone} land</div>
          </div>
        `);
      }
    }).addTo(map);

    // 4. Reservations Layer (VIVID AMBER)
    if (DATA.reservations.features.length > 0) {
      overlayLayers.res = L.geoJSON(DATA.reservations, {
        style: {
          color: '#d97706',
          weight: 2.5,
          fillColor: '#f59e0b',
          fillOpacity: 0.5,
          dashArray: '4, 4'
        },
        onEachFeature: (feature, layer) => {
          const p = feature.properties;
          layer.bindPopup(`
            <div class="custom-popup">
              <h4 style="color:#d97706">🟡 Statutory Reservation</h4>
              <div><b>Code:</b> ${p.code}</div>
              <div><b>Type:</b> ${p.type}</div>
              <div><b>Overlap:</b> ${p.overlap_sqm.toLocaleString()} m² (${p.overlap_percent}%)</div>
            </div>
          `);
        }
      }).addTo(map);
    }

    // 5. Designations Layer (DEEP PURPLE)
    if (DATA.designations.features.length > 0) {
      overlayLayers.des = L.geoJSON(DATA.designations, {
        style: {
          color: '#7c3aed',
          weight: 2.5,
          fillColor: '#8b5cf6',
          fillOpacity: 0.45,
          dashArray: '3, 3'
        },
        onEachFeature: (feature, layer) => {
          const p = feature.properties;
          layer.bindPopup(`
            <div class="custom-popup">
              <h4 style="color:#7c3aed">🟣 Existing Designation</h4>
              <div><b>Code:</b> ${p.code}</div>
              <div><b>Description:</b> ${p.description}</div>
              <div><b>Overlap:</b> ${p.overlap_sqm.toLocaleString()} m² (${p.overlap_percent}%)</div>
            </div>
          `);
        }
      }).addTo(map);
    }

    // 6. Neighbours Layer (SLATE GREY)
    overlayLayers.neigh = L.geoJSON(DATA.neighbors, {
      style: {
        color: '#64748b',
        weight: 1.5,
        fillColor: '#94a3b8',
        fillOpacity: 0.12,
        dashArray: '2, 4'
      },
      onEachFeature: (feature, layer) => {
        layer.bindPopup(`
          <div class="custom-popup">
            <h4>📍 Adjoining Parcel</h4>
            <div><b>CTS Number:</b> ${feature.properties.cts_no}</div>
          </div>
        `);
      }
    }).addTo(map);

    // Initial Zoom Fit
    function fitPlotBounds() {
      if (overlayLayers.plot && overlayLayers.plot.getBounds().isValid()) {
        map.fitBounds(overlayLayers.plot.getBounds(), {
          paddingTopLeft: [390, 30],
          paddingBottomRight: [30, 30],
          maxZoom: 19
        });
      }
    }

    fitPlotBounds();

    // Toggle Overlay Layers
    function toggleOverlay(layerKey) {
      const layer = overlayLayers[layerKey];
      const pill = document.getElementById('layer' + layerKey.charAt(0).toUpperCase() + layerKey.slice(1));
      if (!layer) return;
      if (map.hasLayer(layer)) {
        map.removeLayer(layer);
        if (pill) pill.classList.remove('active');
      } else {
        map.addLayer(layer);
        if (pill) pill.classList.add('active');
      }
    }

    // Toggle HUD
    function toggleHud() {
      const hud = document.getElementById('dossierHud');
      const toggleBtn = document.getElementById('hudToggleBtn');
      hud.classList.toggle('collapsed');
      toggleBtn.style.display = hud.classList.contains('collapsed') ? 'block' : 'none';
    }

    // Measure Tool Mode
    let measureMode = false;
    let measurePoints = [];
    let measureLine = null;

    function toggleMeasureMode() {
      measureMode = !measureMode;
      const btn = document.getElementById('measureBtn');
      if (measureMode) {
        btn.style.background = '#2563eb';
        btn.style.color = '#ffffff';
        map.getContainer().style.cursor = 'crosshair';
      } else {
        btn.style.background = '';
        btn.style.color = '';
        map.getContainer().style.cursor = '';
        if (measureLine) map.removeLayer(measureLine);
        measurePoints = [];
      }
    }

    map.on('click', (e) => {
      if (!measureMode) return;
      measurePoints.push(e.latlng);
      if (measureLine) map.removeLayer(measureLine);
      measureLine = L.polyline(measurePoints, { color: '#2563eb', weight: 3, dashArray: '5, 5' }).addTo(map);
      if (measurePoints.length > 1) {
        let totalDist = 0;
        for (let i = 0; i < measurePoints.length - 1; i++) {
          totalDist += measurePoints[i].distanceTo(measurePoints[i + 1]);
        }
        L.popup()
          .setLatLng(e.latlng)
          .setContent(`<b>Measured Distance:</b> ${totalDist.toFixed(2)} meters (${(totalDist * 3.28084).toFixed(1)} ft)`)
          .openOn(map);
      }
    });
