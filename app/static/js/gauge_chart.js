function loadGaugeChart(complexity_score, mean, stddev) {
    google.charts.load('current', {'packages':['gauge']});
    google.charts.setOnLoadCallback(drawChart);
  
    function drawChart() {
      var data = google.visualization.arrayToDataTable([
        ['Label', 'Value'],
        ['', complexity_score]
      ]);
  
      var options = {
        width: 150, height: 150,
        redFrom: mean, redTo: 100,
        yellowFrom: 9, yellowTo: mean + stddev,
        greenFrom: 0, greenTo: mean - stddev,
        minorTicks: 5,
        max: mean + 2 * stddev
      };
  
      var chart = new google.visualization.Gauge(document.getElementById('gauge_chart'));
      chart.draw(data, options);
    }
  }
  