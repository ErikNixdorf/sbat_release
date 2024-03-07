"""
The plot module which summarizes all the plotting functionality 
"""
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import List, Tuple, Union, Optional
from pathlib import Path
import numpy as np
import logging
from copy import copy
plot_logger = logging.getLogger('sbat.postprocess')
class Plotter:
    def __init__(self,sbat_instance):
        self.source_class = sbat_instance
        
        #depending on what is activated we initialize different plotting schemes
        if self.source_class.config['recession']['activate']:
            plot_logger.info('Plot recession results')
            
            plot_recession_results(meta_data = self.source_class.gauges_meta,
                                   limb_data = self.source_class.recession_limbs_ts,
                                   input_ts = self.source_class.recession_ts,
                                   mrc_curve = self.source_class.master_recession_curves,
                                   parameters_to_plot=['rec_Q0', 'rec_n', 'pearson_r'],
                                   output_dir=Path(self.source_class.paths["output_dir"], 'figures','recession')
                                   )
            
        
def plot_along_streamlines(stream_ts : pd.DataFrame(),
                           stream_name: str = 'river',
                           sort_column: str = 'river_km',
                           para_column: str = 'q_daily',
                           gauge_ticklabels: List[str] = None,                           
                           plot_context='talk',
                           fig_width=10,                           
                           output_dir: Union[str, Path] = Path.cwd() / 'bf_analysis' / 'figures',
                           yaxis_labels=dict({'BF':'BF [$m^{3}$/s]',
                                          'BFI': 'BFI [-]',
                                          'Q': 'Q [$m^{3}$/s]',
                                          'Q*': 'Q* [$m^{3}$/s]'}),
                           ) -> Tuple:
    """
    Plot a line chart of a given parameter (e.g. daily discharge) along the streamlines of a river system,
    and a separate line chart for each decade of data available.

    Parameters:
    -----------
    stream_ts: pd.DataFrame
        A pandas DataFrame containing the data to plot, with one row per gauge station and columns for the
        parameters of interest (e.g. 'q_daily' for daily discharge), the station name and location (e.g. 'station_id',
        'river_km') and the decade of observation (e.g. 'decade').
    stream_name: str, optional (default='river')
        The name of the river system to plot.
    sort_column: str, optional (default='river_km')
        The column of `stream_gauges` to use for sorting the data along the river system. By default, this is the
        river kilometre column.
    para_column: str, optional (default='q_daily')
        The name of the column in `stream_gauges` containing the parameter of interest to plot (e.g. 'q_daily' for daily
        discharge). This column should contain numeric values.
    gauge_ticklabels: list of str, optional (default=[])
        A list of labels to use for the x-axis ticks, one per gauge station. By default, no labels are shown.
    output_dir: str or Path-like, optional (default='bf_analysis/figures')
        The directory where to save the output plots. By default, the plots are saved in a 'bf_analysis/figures'
        subdirectory of the current working directory.

    Returns:
    --------
    None
    """
    
    def _set_title_label(xlabel=str,
                         ylabel=str,
                         xticks=List,
                         gauge_ticklabels=List,
                         title=str):
        ax = plt.gca()
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        ax.set_xticks(xticks)
        plt.xticks(rotation=90)
        if gauge_ticklabels is not None:
            ax.set_xticklabels(gauge_ticklabels)
            
            
    #%%first we check whether there is actually data to plot
    if all([np.isnan(entry) for entry in stream_ts[para_column].unique()]):
        plot_logger.info(f'No estimates for parameter{para_column} in dataset, skip plotting')
        return
    if 'sample_id' not in stream_ts.columns:
        stream_ts['sample_id'] = 0
    if 'bf_method' not in stream_ts.columns:
        stream_ts['bf_method'] = 'default'
    stream_ts_decade = stream_ts.copy().reset_index()
    if 'decade' not in stream_ts_decade.columns:
        stream_ts_decade['decade'] = [x[0:3] + '5' for x in stream_ts_decade['date'].dt.strftime('%Y')]

    xticks= stream_ts[sort_column].unique()
    #if new parameter appears, just integrate as new key value pair
    if para_column not in yaxis_labels.keys():
        yaxis_labels.update({para_column:para_column})

    if gauge_ticklabels is not None:
        sort_label=dict({'river_km':'Gauging Station'})
    else:
        sort_label=dict({'river_km':'Distance from Source [km]'})
        
    #define the subset columns which are the only relevant together with groupby cols
    subset_cols = [para_column,sort_column]
        
    #%%plot over time and generate certain differences of spreading
    groupby_cols = ['gauge']
    data = stream_ts.groupby(groupby_cols)[subset_cols].mean().reset_index()
    
    
    sns.set_context(plot_context)
    fig, ax = plt.subplots(figsize=(fig_width,0.70744 *fig_width))
    sns.lineplot(data=data, x=sort_column, y=para_column,
                      marker='o', linewidth=2, markersize=10, color='dodgerblue')
    # we give an error band if available
    stream_ts=stream_ts.sort_values(sort_column)
    ax.fill_between(stream_ts.groupby('gauge').first().sort_values(sort_column)[sort_column], 
                    stream_ts.groupby(sort_column)[para_column].mean().sort_index() - stream_ts.groupby(sort_column)[para_column].std().sort_index(),
                    stream_ts.groupby(sort_column)[para_column].mean().sort_index() + stream_ts.groupby(sort_column)[para_column].std().sort_index(), 
                    alpha=0.2, color='k')
    
    _set_title_label(xlabel=sort_label[sort_column],
                         ylabel=yaxis_labels[para_column],
                         xticks=xticks,
                         gauge_ticklabels=gauge_ticklabels,
                         title=f'Mean {para_column} at {stream_name}')
    
    plt.tight_layout()
    fig.savefig(Path(output_dir, f'{stream_name}_{para_column.replace("*","")}_mean_along_streamlines.png'), dpi=300)
    plt.close()
    
    
    #%%make a plot of the CV value
    cv_col_name = f'{para_column}_cv'
    groupby_cols = ['gauge']
    data = stream_ts.groupby(groupby_cols)[subset_cols].mean(numeric_only=True).reset_index()
    data_std = stream_ts.groupby(groupby_cols)[para_column].std().reset_index()
    data[cv_col_name] =  data_std[para_column]/ data[para_column]
    
    sns.set_context(plot_context)
    fig, ax = plt.subplots(figsize=(fig_width,0.70744 *fig_width))
    sns.lineplot(data=data, x=sort_column, y=cv_col_name,
                      marker='o', linewidth=2, markersize=10, color='red')

    _set_title_label(xlabel=sort_label[sort_column],
                         ylabel=cv_col_name+ ' [-]',
                         xticks=xticks,
                         gauge_ticklabels=gauge_ticklabels,
                         title=f'{cv_col_name} at {stream_name}')

    plt.tight_layout()
    fig.savefig(Path(output_dir, f'{stream_name}_{cv_col_name.replace("*","")}_along_streamlines.png'), dpi=300)
    plt.close()
    
    
    #cv plot with decade
    groupby_cols = ['gauge','decade']    
    data = stream_ts.groupby(groupby_cols)[subset_cols].mean(numeric_only=True).reset_index()
    data_std = stream_ts.groupby(groupby_cols)[para_column].std().reset_index()
    data[cv_col_name] =  data_std[para_column]/ data[para_column]
    
    if all([np.isnan(entry) for entry in data[cv_col_name].unique()]):
        plot_logger.info(f'No estimates for parameter{cv_col_name} in dataset, skip plotting')
        
    else:
    
        sns.set_context(plot_context)
        fig, ax = plt.subplots(figsize=(fig_width,0.70744 *fig_width))
        sns.lineplot(data=data, x=sort_column, y=cv_col_name,hue='decade',
                          marker='o', linewidth=2, markersize=10, 
                          palette='rocket',
                          hue_order=data['decade'].sort_values())

        _set_title_label(xlabel=sort_label[sort_column],
                         ylabel=cv_col_name+ ' [-]',
                         xticks=xticks,
                         gauge_ticklabels=gauge_ticklabels,
                         title=f'{cv_col_name} at {stream_name} per decade')

        plt.tight_layout()
        fig.savefig(Path(output_dir, f'{stream_name}_{cv_col_name.replace("*","")}_decade_along_streamlines.png'), dpi=300)
        plt.close()
    
    
    #%% Next we make a lineplot where we show the confidence interval from the sampling
    #process
    groupby_cols = ['gauge','sample_id','bf_method']
    data = stream_ts.groupby(groupby_cols)[subset_cols].mean().reset_index()
    #plot
    sns.set_context(plot_context)
    fig, ax = plt.subplots(figsize=(fig_width,0.70744 *fig_width))
    sns.lineplot(data=data, x=sort_column, y=para_column, hue = 'bf_method',
                      marker='o', linewidth=2, markersize=10, palette='mako_r',errorbar=("pi", 100),err_style='bars')

    _set_title_label(xlabel=sort_label[sort_column],
                     ylabel=yaxis_labels[para_column],
                     xticks=xticks,
                     gauge_ticklabels=gauge_ticklabels,
                     title=f'Average {para_column} per method at {stream_name}')

    plt.tight_layout()
    fig.savefig(Path(output_dir, f'{stream_name}_{para_column.replace("*","")}_method_dependence_mean_along_streamlines.png'), dpi=300)
    plt.close()
    
    
    #%% We plot over each decade with error style band 
    groupby_cols = ['gauge','sample_id','decade']
    data = stream_ts_decade.groupby(groupby_cols)[subset_cols].mean().reset_index()

    #plot for each decade
    fig, ax = plt.subplots(figsize=(fig_width,0.70744 *fig_width))
    sns.lineplot(data=data, x=sort_column, y=para_column, hue='decade',
                      marker='o', linewidth=2, markersize=10, 
                      palette='rocket',
                      errorbar=("pi", 100),
                      err_style='bars',
                      hue_order=data['decade'].sort_values())
    
    _set_title_label(xlabel=sort_label[sort_column],
                     ylabel=yaxis_labels[para_column],
                     xticks=xticks,
                     gauge_ticklabels=gauge_ticklabels,
                     title=f'{para_column} at {stream_name} and decade')
    
    plt.tight_layout()
    fig.savefig(Path(output_dir, f'{stream_name}_{para_column.replace("*","")}_decadal_along_streamlines.png'), dpi=300)
    plt.close()
    
    return None




def plot_recession_results(meta_data: pd.DataFrame, 
                           limb_data: pd.DataFrame, 
                           input_ts: pd.DataFrame,
                           mrc_curve: pd.DataFrame, 
                           parameters_to_plot: list[str] = ['Q0', 'pearson_r', 'n'],
                           output_dir: Path = Path(Path.cwd(), 'bf_analysis', 'figures')
                           )-> None:
    """
    Plot the results of the baseflow calculation.

    Parameters
    ----------
    meta_data : pandas.DataFrame
        Metadata for each gauge station, with columns 'gauge', 'lat', 'lon', 'stream', 'distance_to_mouth', and 'altitude'.
    limb_data : pandas.DataFrame
        Dataframe containing recession limb parameters for each gauge station and limb, with columns 'gauge', 'section_id',
        'decade', 'Q0', 'pearson_r', 'n', 'a', 'b', 'k', and 'Q_interp'.
    input_ts : pandas.DataFrame
        Time series of water flow for each gauge station, with columns representing dates and rows representing water flow values.
    mrc_curve : pandas.DataFrame
        Master recession curve for each gauge station, with columns 'gauge', 'section_id', 'decade', 'section_time', and 'q_rec'.
    parameters_to_plot : list of str, optional
        List of the names of the parameters to plot along the streamlines. Default is ['Q0', 'pearson_r', 'n'].
    output_dir : pathlib.Path, optional
        Output directory to save the generated figures. Default is 'bf_analysis/figures' in the current working directory.

    Returns
    -------
    None
    """
    #set up
    # first we generate the output dir
    output_dir.mkdir(parents=True, exist_ok=True)
    #default seaborn setting
    sns.set_context('paper')
    
    #convert the time series data
    
    #%% lets plot the parameters along the streamline
    #convert time series data
    streams_ts=input_ts.drop(columns='decade').reset_index().melt(id_vars='date',var_name='gauge').set_index('date')
    #add the relevant columns
    streams_ts['decade'] = [x[0:3] + '5' for x in streams_ts.index.strftime('%Y')]
    plot_logger.info('Plotting the mrc recession parameters along the streamline')
    for stream,stream_gauges in meta_data.reset_index().groupby('stream'):        
        #get river km
        stream_gauges['river_km'] = stream_gauges['distance_to_mouth'].max() - stream_gauges[
            'distance_to_mouth']
        stream_gauges = stream_gauges.sort_values('river_km')
        gauge_ticklabels = [label.split('_')[0] for label in stream_gauges['gauge'].unique()]
        
        #merge all properties of stream_gauges on stream_ts
        transfer_props=copy(parameters_to_plot)
        transfer_props.extend(['river_km','gauge'])
        stream_ts = streams_ts[streams_ts['gauge'].isin(stream_gauges['gauge'])]
        stream_ts = pd.merge(stream_ts,stream_gauges[transfer_props],on='gauge',how='left')

        for para_col in parameters_to_plot:
            
            #check whether data on the parameter exists otherwise

            plot_along_streamlines(stream_ts = stream_ts,
                                       stream_name = stream+'_mrc_',
                                       sort_column = 'river_km',
                                       para_column = para_col,
                                       gauge_ticklabels = gauge_ticklabels,
                                       output_dir = output_dir)

    #%% We provide a boxplot to get the individual limbs
    plot_logger.info('Plotting the recession parameters of the individual limbs')
    for gauge_name,subset in limb_data.groupby('gauge'):
        for parameter_to_plot in parameters_to_plot:
            #check whether we have more than 1, e.g by using multiple reservoirs
            para_cols =[col for col in subset.columns if parameter_to_plot in col]
            if len(para_cols)==0:                
                continue
            else:
                for parameter_name in para_cols:                    
                    fig, ax = plt.subplots()
                    sns.boxplot(data=subset, x='gauge', y=parameter_name)
                    plt.xticks(rotation=90)
                    plt.xlabel('gauge')
                    plt.ylabel(parameter_name)
                    plt.title(f'{parameter_name} boxplot at {gauge_name}')
                    plt.tight_layout()
                    fig.savefig(Path(output_dir, f'{gauge_name}_boxplot_{parameter_name}.png'), dpi=300)
                    plt.close()
                    #across all decades
                    fig, ax = plt.subplots()
                    sns.boxplot(data=subset.reset_index(), x=parameter_name,y='decade')
                    plt.title(f'{parameter_name} decade boxplot at {gauge_name}')
                    plt.tight_layout()
                    fig.savefig(Path(output_dir, f'{gauge_name}_decade_boxplot_{parameter_name}.png'), dpi=300)
                    plt.close()
    #%% plot the time series and the location of the limbs

    plot_logger.info('Plotting the time series of input data and recession limbs')
    if 'decade' in input_ts.columns:
        input_ts=input_ts.drop(columns=['decade'])
    
    for gauge_name,limb_subset in limb_data.groupby('gauge'):
        input_ts_subset=input_ts.loc[:,gauge_name]
        fig,p1=plt.subplots()
        input_ts_subset.plot(linewidth=2,ax=p1)
        
        for grouper,section in limb_subset.groupby(['section_id','decade']):
            section=section.set_index('date')['Q_interp']
            section.plot(ax=p1.axes,linestyle='--',color='k',linewidth=0.5)
            p1.axes.axvline(x=section.index[0],color='grey',linewidth=0.2, alpha = 0.5)
            p1.axes.axvline(x=section.index[-1],color='grey',linewidth=0.2, alpha = 0.5)
            p1.axes.text(x=section.index.mean(),
                         y=section.max(),
                         s=str(grouper[0]),
                         horizontalalignment='center',
                         )
        
        plt.ylabel('water flow')
        plt.xlabel('date')
        plt.title(f'Time_series with recession limbs at {gauge_name}')
        h,l = p1.get_legend_handles_labels()
        plt.legend(h[:2], l[:2])
        plt.tight_layout()
        fig=p1.figure        
        fig.savefig(Path(output_dir, f'{gauge_name}_flow_timeseries_with_recession_limbs.png'), dpi=300)
        plt.close()

    
    #%% plot the master curve per decade
    for gauge_name,subset in mrc_curve.groupby('gauge'):
        fig, ax = plt.subplots()
        sns.lineplot(data=subset,x='section_time',y='q_rec',hue='decade')
        plt.xlabel('timestep_from_peak')
        plt.ylabel('water flow')
        plt.title(f'MRC Curve per decade at gauge {gauge_name}')
        plt.tight_layout()
        fig.savefig(Path(output_dir, f'{gauge_name}_mrc_decadal_curves.png'), dpi=300)
        plt.close()
    
    return None
