var lagopusChartColors = {
    red: 'rgb(255, 99, 132)',
    orange: 'rgb(255, 159, 64)',
    yellow: 'rgb(255, 205, 86)',
    green: 'rgb(75, 192, 192)',
    blue: 'rgb(54, 162, 235)',
    purple: 'rgb(153, 102, 255)',
    grey: 'rgb(201, 203, 207)',
    white: 'rgb(255, 255, 255)'
};

/*
 * Specify a Canvas element to turn it into a live chart of execs / sec
 */
function lagopus_job_aflstat(ctx, jobid) {
    var color = Chart.helpers.color;

    var chart = new Chart(ctx, {
      type: 'line',
      data: {
        datasets: [
        {
            influx_column: 'total_paths',
            label: 'Total paths',
            pointRadius: 1,
            backgroundColor: color(lagopusChartColors.grey).alpha(0.3).rgbString(),
            fill: true,
            data: []
        },
        {
            influx_column: 'current_path',
            label: 'Current path',
            pointRadius: 1,
            backgroundColor: color(lagopusChartColors.white).alpha(0.4).rgbString(),
            fill: true,
            data: []
        },
        {
            influx_column: 'pending',
            label: 'Pending paths',
            pointRadius: 1,
            backgroundColor: color(lagopusChartColors.blue).alpha(0.5).rgbString(),
            fill: true,
            data: []
        },
        {
            influx_column: 'pending_fav',
            label: 'Pending favored paths',
            pointRadius: 1,
            backgroundColor: color(lagopusChartColors.red).alpha(0.8).rgbString(),
            fill: true,
            data: []
        }
        ]
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          yAxes: [{
            ticks: {
              suggestedMin: 0,
              suggestedMax: 500,
            }
          }],
          xAxes: [{
              type: 'time',
              time: {
                  displayFormats: {
                      second: 'h:mm:ss'
                  }
              },
              distribution: 'series',
              bounds: 'data'
          }]
        }
      }
    });

    function updategraph(){
        $.ajax({
            type: "get",
            url: "api/jobs/stats?job=" + jobid,
            success:function(data)
            {
                console.log(data);
                chart.data.datasets.forEach((dataset) => {
                        dataset.data = data.map(function(point) {
                                return {
                                        x: new moment(point['time']),
                                        y: point[dataset['influx_column']]
                                };
                        });
                });
                chart.update();
                setTimeout(function(){
                    updategraph();
                }, 5000);
            }
        });
    }
    updategraph();
}

function lagopus_job_aflperf(ctx, jobid) {
    var color = Chart.helpers.color;

    var chart = new Chart(ctx, {
      type: 'line',
      data: {
        datasets: [
        {
            influx_column: 'execs_per_sec',
            label: 'Execs / sec',
            pointRadius: 1,
            backgroundColor: color(lagopusChartColors.blue).alpha(0.6).rgbString(),
            fill: true,
            data: []
        }
        ]
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          yAxes: [{
            stacked: true,
            ticks: {
              suggestedMin: 0,
              suggestedMax: 500,
            }
          }],
          xAxes: [{
              type: 'time',
              time: {
                  displayFormats: {
                      second: 'h:mm:ss'
                  }
              },
              distribution: 'series',
              bounds: 'data'
          }]
        }
      }
    });

    function updategraph(){
        $.ajax({
            type: "get",
            url: "api/jobs/stats?job=" + jobid,
            success:function(data)
            {
                console.log(data);
                chart.data.datasets.forEach((dataset) => {
                        dataset.data = data.map(function(point) {
                                return {
                                        x: new moment(point['time']),
                                        y: point[dataset['influx_column']]
                                };
                        });
                });
                chart.update();
                setTimeout(function(){
                    updategraph();
                }, 5000);
            }
        });
    }
    updategraph();
}
