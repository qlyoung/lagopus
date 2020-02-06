var lagopusChartColors = {
    red: 'rgb(255, 99, 132)',
    orange: 'rgb(255, 159, 64)',
    yellow: 'rgb(255, 205, 86)',
    green: 'rgb(75, 192, 192)',
    blue: 'rgb(54, 162, 235)',
    purple: 'rgb(153, 102, 255)',
    grey: 'rgb(201, 203, 207)'
};

/*
 * Specify a Canvas element to turn it into a live chart of execs / sec
 */
function lagopus_job_stat_chart(ctx, jobid, statname, label) {
    var color = Chart.helpers.color;

    var myChart = new Chart(ctx, {
      type: 'line',
      data: {
        datasets: [{
            label: label,
            pointRadius: 1,
            backgroundColor: color(lagopusChartColors.blue).alpha(0.4).rgbString(),
            fill: true,
            data: []
        }]
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          yAxes: [{
            ticks: {
              suggestedMin: 0,
              suggestedMax: 3000
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
                myChart.data.datasets[0].data = data.map(function(point) {
                    return {
                        x: new moment(point['time']),
                        y: point[statname]
                    };
                }).slice(-20);
                myChart.update();
                setTimeout(function(){
                    updategraph();
                }, 5000);
            }
        });
    }
    updategraph();
}
